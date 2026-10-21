//! Состояние БД (`engine/adapters/db.py`): таблицы дампа `db-after-warmup.sql.gz`, `fork` на сценарий.
//!
//! Дамп читается как latin1: байт = символ, поэтому любые байты MySQL не ломают разбор. Значения ячеек —
//! `null`, целое, дробное или строка (как `None`/`int`/`float`/`str` в Python).

use std::io::Read;
use std::path::Path;

use anyhow::{Context, Result};
use flate2::read::GzDecoder;
use indexmap::IndexMap;
use regex::Regex;
use archonity_model::pyfmt::splitlines;
use archonity_model::values::Value;
use serde_json::Value as Json;

/// Строка таблицы: колонка -> ячейка. Порядок колонок как в `CREATE TABLE`.
pub type Row = IndexMap<String, Value>;

#[derive(Clone, Debug, Default)]
pub struct DatabaseState {
    pub tables: IndexMap<String, Vec<Row>>,
    pub table_aliases: IndexMap<String, String>,
    pub table_columns: IndexMap<String, Vec<String>>,
}

impl DatabaseState {
    /// Имя таблицы после первой точки: `orders`, `<db>.orders`, `res:table:<service>.orders`.
    pub fn normalize_table_name(&self, table_name: &str) -> String {
        if table_name.is_empty() {
            return String::new();
        }
        if let Some(a) = self.table_aliases.get(table_name) {
            return a.clone();
        }
        let t = table_name.strip_prefix("res:table:").unwrap_or(table_name);
        match t.split_once('.') {
            Some((_, rest)) => rest.to_string(),
            None => t.to_string(),
        }
    }

    pub fn get_table(&self, table_name: &str) -> &[Row] {
        let c = self.normalize_table_name(table_name);
        self.tables.get(&c).map(Vec::as_slice).unwrap_or(&[])
    }

    pub fn has_table(&self, table_name: &str) -> bool {
        self.tables.contains_key(&self.normalize_table_name(table_name))
    }

    pub fn get_columns(&self, table_name: &str) -> Vec<String> {
        let c = self.normalize_table_name(table_name);
        self.table_columns.get(&c).cloned().unwrap_or_default()
    }

    pub fn table_names(&self) -> Vec<String> {
        let mut v: Vec<String> = self.tables.keys().cloned().collect();
        v.sort();
        v
    }

    pub fn insert(&mut self, table_name: &str, row: Row) {
        let c = self.normalize_table_name(table_name);
        self.tables.entry(c).or_default().push(row);
    }

    /// Изменяемая таблица (для `update`/`delete` мира).
    pub fn table_mut(&mut self, table_name: &str) -> Option<&mut Vec<Row>> {
        let c = self.normalize_table_name(table_name);
        self.tables.get_mut(&c)
    }

    /// Независимая копия: мир сценария и откат шага.
    pub fn fork(&self) -> DatabaseState {
        self.clone()
    }
}


/// Разбор `VALUES (...), (...)` одним проходом (`_parse_sql_values`). Вход и выход — latin1-символы.
fn parse_sql_values(s: &str) -> Vec<Vec<Value>> {
    let b: Vec<char> = s.chars().collect();
    let n = b.len();
    let mut rows = Vec::new();
    let mut i = 0;
    let ws = |c: char| matches!(c, ' ' | '\t' | '\r' | '\n');
    while i < n {
        while i < n && b[i] != '(' {
            i += 1;
        }
        if i >= n {
            break;
        }
        i += 1;
        let mut row: Vec<Value> = Vec::new();
        while i < n {
            while i < n && ws(b[i]) {
                i += 1;
            }
            if i >= n {
                break;
            }
            let ch = b[i];
            if ch == ')' {
                i += 1;
                rows.push(row);
                break;
            } else if ch == ',' {
                i += 1;
                continue;
            } else if ch == '\'' {
                i += 1;
                let mut chars = String::new();
                while i < n {
                    let c = b[i];
                    if c == '\\' {
                        i += 1;
                        if i < n {
                            chars.push(match b[i] {
                                '0' => '\0',
                                'b' => '\x08',
                                'n' => '\n',
                                'r' => '\r',
                                't' => '\t',
                                'Z' => '\x1a',
                                e => e,
                            });
                            i += 1;
                        }
                    } else if c == '\'' {
                        if i + 1 < n && b[i + 1] == '\'' {
                            chars.push('\'');
                            i += 2;
                        } else {
                            i += 1;
                            break;
                        }
                    } else {
                        chars.push(c);
                        i += 1;
                    }
                }
                row.push(Value::string(chars));
            } else if starts_with(&b, i, "_binary '") {
                i += 9;
                let mut chars = String::new();
                while i < n {
                    let c = b[i];
                    if c == '\\' {
                        i += 1;
                        if i < n {
                            chars.push(b[i]);
                            i += 1;
                        }
                    } else if c == '\'' {
                        i += 1;
                        break;
                    } else {
                        chars.push(c);
                        i += 1;
                    }
                }
                row.push(Value::string(chars));
            } else if starts_with(&b, i, "NULL") {
                row.push(Value::Null);
                i += 4;
            } else {
                let start = i;
                while i < n && b[i] != ',' && b[i] != ')' {
                    i += 1;
                }
                let token: String = b[start..i].iter().collect::<String>().trim().to_string();
                row.push(number_or_str(&token));
            }
            while i < n && ws(b[i]) {
                i += 1;
            }
            if i < n && b[i] == ',' {
                i += 1;
            }
        }
    }
    rows
}

fn starts_with(b: &[char], i: usize, pat: &str) -> bool {
    let mut j = i;
    for c in pat.chars() {
        if j >= b.len() || b[j] != c {
            return false;
        }
        j += 1;
    }
    true
}

fn number_or_str(token: &str) -> Value {
    if token.contains('.') {
        match token.parse::<f64>() {
            Ok(f) => Value::Float(f),
            Err(_) => Value::str(token),
        }
    } else if let Ok(i) = token.parse::<i64>() {
        Value::Int(i)
    } else {
        Value::str(token)
    }
}

fn latin1(bytes: &[u8]) -> String {
    bytes.iter().map(|&b| b as char).collect()
}

/// `context/db-after-warmup.sql.gz` -> таблицы.
pub fn load_db_dump(gz_path: &Path) -> Result<DatabaseState> {
    let raw = std::fs::read(gz_path).with_context(|| format!("Database dump file not found: {}", gz_path.display()))?;
    let mut bytes = Vec::new();
    GzDecoder::new(&raw[..]).read_to_end(&mut bytes).context("gzip")?;
    let text = latin1(&bytes);

    let lines = splitlines(&text);
    let use_re = Regex::new(r"(?i)^USE\s+`?([^;`]+)`?;").unwrap();
    let create_re = Regex::new(r"(?i)^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([a-zA-Z0-9_.]+)`?").unwrap();
    let mut current_db = "default".to_string();
    let mut table_cols: IndexMap<String, Vec<String>> = IndexMap::new();
    let mut table_to_db: IndexMap<String, String> = IndexMap::new();

    let mut i = 0;
    while i < lines.len() {
        let line = lines[i].trim();
        if line.is_empty() {
            i += 1;
            continue;
        }
        if line.to_uppercase().starts_with("USE ") {
            if let Some(m) = use_re.captures(line) {
                current_db = m[1].to_string();
            }
            i += 1;
            continue;
        }
        if line.to_uppercase().starts_with("CREATE TABLE") {
            let name = create_re.captures(line).map(|m| m[1].to_string()).unwrap_or_else(|| "unknown".to_string());
            let mut cols = Vec::new();
            i += 1;
            while i < lines.len() {
                let l = lines[i].trim();
                if l.starts_with(')') && (l.to_uppercase().contains("ENGINE") || l.contains(';')) {
                    i += 1;
                    break;
                }
                if l.starts_with('`') {
                    if let Some(col) = l.split('`').nth(1) {
                        cols.push(col.to_string());
                    }
                }
                i += 1;
            }
            table_cols.insert(name.clone(), cols);
            table_to_db.insert(name, current_db.clone());
            continue;
        }
        i += 1;
    }

    let insert_re =
        Regex::new(r"(?is)INSERT\s+INTO\s+`?([a-zA-Z0-9_.]+)`?\s*(?:\(([^)]+)\))?\s*VALUES\s*(.*?);").unwrap();
    let mut tables: IndexMap<String, Vec<Row>> = table_cols.keys().map(|t| (t.clone(), Vec::new())).collect();
    for m in insert_re.captures_iter(&text) {
        let tbl = m[1].to_string();
        let val_clause = &m[3];
        let cols = table_cols.get(&tbl).cloned().unwrap_or_default();
        let rows = parse_sql_values(val_clause);
        let dest = tables.entry(tbl).or_default();
        for vals in rows {
            let mut row = Row::new();
            if !cols.is_empty() {
                for (c, v) in cols.iter().zip(vals) {
                    row.insert(c.clone(), v);
                }
            } else {
                for (idx, v) in vals.into_iter().enumerate() {
                    row.insert(format!("col_{idx}"), v);
                }
            }
            dest.push(row);
        }
    }

    let mut aliases = IndexMap::new();
    for (tbl, db) in &table_to_db {
        aliases.insert(tbl.clone(), tbl.clone());
        aliases.insert(format!("{db}.{tbl}"), tbl.clone());
    }
        Ok(DatabaseState { tables, table_aliases: aliases, table_columns: table_cols })
}

/// Поле `context` скелета (или `context/README.md`): пассажир, даты, баланс (`parse_context`).
pub fn parse_context(text: &str) -> IndexMap<String, Json> {
    let mut info = IndexMap::new();
    let month = |name: &str| -> Option<&'static str> {
        Some(match name {
            "january" => "01",
            "february" => "02",
            "march" => "03",
            "april" => "04",
            "may" => "05",
            "june" => "06",
            "july" => "07",
            "august" => "08",
            "september" => "09",
            "october" => "10",
            "november" => "11",
            "december" => "12",
            _ => return None,
        })
    };
    for (key, lead) in [("travel_date", "booked for"), ("system_date", "system clock is")] {
        let re_text = Regex::new(&format!(r"(?i){lead}\s+([0-9]{{1,2}})\s+([A-Za-z]+)\s+([0-9]{{4}})")).unwrap();
        if let Some(m) = re_text.captures(text) {
            let day: i64 = m[1].parse().unwrap_or(0);
            if let Some(mo) = month(&m[2].to_lowercase()) {
                info.insert(key.to_string(), Json::String(format!("{}-{}-{:02}", &m[3], mo, day)));
            }
        } else {
            let re_iso = Regex::new(&format!(r"(?i){lead}\s+([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})")).unwrap();
            if let Some(m) = re_iso.captures(text) {
                info.insert(key.to_string(), Json::String(m[1].to_string()));
            }
        }
    }
    let user = Regex::new(r"(?i)pre-registered user\s+([a-zA-Z0-9_-]+)").unwrap();
    if let Some(m) = user.captures(text) {
        info.insert("user_name".to_string(), Json::String(m[1].to_string()));
    }
    let bal = Regex::new(r"(?i)(?:account balance|balance)\s+([0-9]+(?:[\s,][0-9]{3})*(?:\.[0-9]+)?)").unwrap();
    if let Some(m) = bal.captures(text) {
        let t = m[1].replace([' ', ','], "");
        if let Ok(f) = t.parse::<f64>() {
            if let Some(n) = serde_json::Number::from_f64(f) {
                info.insert("balance".to_string(), Json::Number(n));
            }
        }
    }
    info
}

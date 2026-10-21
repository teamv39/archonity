//! Типы и мир БД исполнителя (`engine/executor/world.py`).
//!
//! База — форк дампа на сценарий. Строка таблицы превращается в объект сущности по полям класса из скелета
//! (`@Column`, встраиваемые типы, enum по порядковому номеру, коллекции в отдельных таблицах).

use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use archonity_model::names::camel_to_snake;
use archonity_model::pyfmt::splitlines;
use archonity_model::values::{
    py_float, py_str, py_truthy, shared, Obj, Shared, Tri, Value,
};
use indexmap::IndexMap;
use regex::Regex;
use serde_json::Value as Json;

use crate::db::{DatabaseState, Row};
use crate::jx;
use crate::skeleton::Node;

thread_local! {
    static UUID: Cell<u64> = const { Cell::new(1) };
}

pub fn snake(name: &str) -> String {
    camel_to_snake(name)
}

pub fn camel(col: &str) -> String {
    let mut parts = col.split('_');
    let head = parts.next().unwrap_or("");
    let mut out = head.to_string();
    for p in parts {
        let mut cs = p.chars();
        if let Some(f) = cs.next() {
            out.extend(f.to_uppercase());
            out.push_str(cs.as_str());
        }
    }
    out
}

/// `UUID.randomUUID()` исполнителя: детерминированный и валидный для `UUID.fromString`. Счётчик общий на процесс.
pub fn fresh_uuid() -> String {
    UUID.with(|c| {
        let n = c.get();
        c.set(n + 1);
        format!("00000000-0000-4000-8000-{n:012}")
    })
}

/// Литералы аргументов константы enum: `("G", 1)` -> `["G", 1]`.
pub fn parse_java_args(text: &str) -> Vec<Value> {
    thread_local! {
        static LIT: Regex = Regex::new(r#""((?:[^"\\]|\\.)*)"|(-?\d+\.\d*|-?\d*\.\d+)[dDfF]?|(-?\d+)[lL]?|(true|false|null)"#).unwrap();
    }
    LIT.with(|re| {
        re.captures_iter(text)
            .map(|m| {
                if let Some(g) = m.get(1) {
                    Value::str(g.as_str())
                } else if let Some(g) = m.get(2) {
                    Value::Float(g.as_str().parse().unwrap_or(f64::NAN))
                } else if let Some(g) = m.get(3) {
                    g.as_str().parse::<i64>().map(Value::Int).unwrap_or(Value::Unknown)
                } else {
                    match m.get(4).unwrap().as_str() {
                        "true" => Value::Bool(true),
                        "false" => Value::Bool(false),
                        _ => Value::Null,
                    }
                }
            })
            .collect()
    })
}

/// Колонка поля: `@Column(name=..)` / `@JoinColumn(name=..)`, иначе `snake(имя)`.
pub fn column_of(field: &Node) -> String {
    thread_local! {
        static NAME: Regex = Regex::new(r#"name\s*=\s*"([^"]+)""#).unwrap();
    }
    for a in jx::arr(field, "annotations") {
        if matches!(jx::str_(a, "name"), Some("Column") | Some("JoinColumn")) {
            if let Some(m) = NAME.with(|re| re.captures(jx::str_(a, "args").unwrap_or("")).map(|c| c[1].to_string())) {
                return m;
            }
        }
    }
    snake(jx::str_(field, "name").unwrap_or(""))
}

/// Индекс типов проекта: поля по порядку объявления, колонки, enum-константы, методы.
pub struct TypeIndex {
    pub nodes: Rc<IndexMap<String, Node>>,
    pub types: IndexMap<String, Node>,
    by_fqn: IndexMap<String, Vec<String>>,
    by_simple: IndexMap<String, Vec<String>>,
    pub fields: IndexMap<String, Vec<Node>>,
    pub methods: IndexMap<String, Vec<String>>,
    pub super_of: IndexMap<String, String>,
    deps: IndexMap<String, Vec<String>>,
    shared: Vec<String>,
    targets_root: Option<PathBuf>,
    enum_consts: RefCell<HashMap<String, Rc<Vec<(String, Vec<Value>)>>>>,
    all_fields_cache: RefCell<HashMap<String, Rc<Vec<Node>>>>,
    method_of_cache: RefCell<HashMap<(String, String, Option<usize>), Option<String>>>,
}

impl TypeIndex {
    pub fn new(nodes: Rc<IndexMap<String, Node>>, edges: &[Json], targets_root: Option<&Path>) -> TypeIndex {
        let mut types = IndexMap::new();
        let mut by_fqn: IndexMap<String, Vec<String>> = IndexMap::new();
        let mut by_simple: IndexMap<String, Vec<String>> = IndexMap::new();
        let mut fields: IndexMap<String, Vec<Node>> = IndexMap::new();
        let mut methods: IndexMap<String, Vec<String>> = IndexMap::new();
        for (nid, n) in nodes.iter() {
            match jx::str_(n, "kind") {
                Some("type") => {
                    types.insert(nid.clone(), n.clone());
                    let fqn = jx::str_(n, "fqn").unwrap_or("");
                    by_fqn.entry(fqn.to_string()).or_default().push(nid.clone());
                    let simple = fqn.rsplit('.').next().unwrap_or("").rsplit('$').next().unwrap_or("");
                    by_simple.entry(simple.to_string()).or_default().push(nid.clone());
                }
                Some("field") => {
                    let mut f = n.clone();
                    if let Some(o) = f.as_object_mut() {
                        o.insert("id".to_string(), Json::String(nid.clone()));
                    }
                    fields.entry(jx::str_(n, "owner").unwrap_or("").to_string()).or_default().push(f);
                }
                Some("method") => {
                    methods.entry(jx::str_(n, "owner").unwrap_or("").to_string()).or_default().push(nid.clone());
                }
                _ => {}
            }
        }
        for fl in fields.values_mut() {
            fl.sort_by_key(|f| jx::int(f, "line").unwrap_or(0));
        }
        let mut super_of = IndexMap::new();
        let mut deps: IndexMap<String, Vec<String>> = IndexMap::new();
        for e in edges {
            let (src, tgt) = (jx::str_(e, "source").unwrap_or(""), jx::str_(e, "target").unwrap_or(""));
            match jx::str_(e, "type") {
                Some("extends") if nodes.contains_key(tgt) => {
                    super_of.insert(src.to_string(), tgt.to_string());
                }
                Some("depends_on") => {
                    deps.entry(src.strip_prefix("module:").unwrap_or(src).to_string())
                        .or_default()
                        .push(tgt.strip_prefix("module:").unwrap_or(tgt).to_string());
                }
                _ => {}
            }
        }
        let mut shared: Vec<String> = deps.values().flatten().cloned().collect();
        shared.sort();
        shared.dedup();
        TypeIndex {
            nodes,
            types,
            by_fqn,
            by_simple,
            fields,
            methods,
            super_of,
            deps,
            shared,
            targets_root: targets_root.map(Path::to_path_buf),
            enum_consts: RefCell::new(HashMap::new()),
            all_fields_cache: RefCell::new(HashMap::new()),
            method_of_cache: RefCell::new(HashMap::new()),
        }
    }

    /// Модуль вызывающего, затем его зависимости (без известного модуля или зависимостей — общие библиотеки).
    fn prefs(&self, module: Option<&str>) -> Vec<Option<String>> {
        let deps = self.deps.get(module.unwrap_or("")).filter(|d| !d.is_empty()).unwrap_or(&self.shared);
        std::iter::once(module.map(str::to_string)).chain(deps.iter().cloned().map(Some)).collect()
    }

    fn module_of_type(&self, id: &str) -> Option<&str> {
        self.types.get(id).and_then(|t| jx::str_(t, "module"))
    }

    /// ID узла типа по полному имени: сначала модуль вызывающего, потом его зависимости, потом любой.
    pub fn resolve(&self, fqn: Option<&str>, module: Option<&str>) -> Option<String> {
        let fqn = fqn.filter(|f| !f.is_empty())?;
        let ids = self.by_fqn.get(fqn).filter(|v| !v.is_empty())?;
        if ids.len() == 1 {
            return Some(ids[0].clone());
        }
        for pref in self.prefs(module) {
            if let Some(p) = pref.filter(|p| !p.is_empty()) {
                for i in ids {
                    if self.module_of_type(i) == Some(p.as_str()) {
                        return Some(i.clone());
                    }
                }
            }
        }
        Some(ids[0].clone())
    }

    /// Тип по простому имени в модуле (для `instanceof` и `new` без fqn).
    pub fn resolve_simple(&self, simple: &str, module: Option<&str>) -> Option<String> {
        let cands = self.by_simple.get(simple).filter(|v| !v.is_empty())?;
        for pref in self.prefs(module) {
            for i in cands {
                if self.module_of_type(i) == pref.as_deref() {
                    return Some(i.clone());
                }
            }
        }
        Some(cands[0].clone())
    }

    /// Нестатические поля типа и суперклассов, суперклассы первыми.
    pub fn all_fields(&self, type_id: Option<&str>) -> Rc<Vec<Node>> {
        let Some(tid) = type_id.filter(|t| !t.is_empty()) else { return Rc::new(Vec::new()) };
        if let Some(c) = self.all_fields_cache.borrow().get(tid) {
            return c.clone();
        }
        let mut out: Vec<Node> = Vec::new();
        let mut seen = std::collections::HashSet::new();
        let mut t = Some(tid.to_string());
        while let Some(cur) = t {
            if !seen.insert(cur.clone()) {
                break;
            }
            let own: Vec<Node> = self
                .fields
                .get(&cur)
                .map(|fs| fs.iter().filter(|f| !jx::strs(f, "modifiers").contains(&"static")).cloned().collect())
                .unwrap_or_default();
            out.splice(0..0, own);
            t = self.super_of.get(&cur).cloned();
        }
        let rc = Rc::new(out);
        self.all_fields_cache.borrow_mut().insert(tid.to_string(), rc.clone());
        rc
    }

    pub fn is_enum(&self, type_id: Option<&str>) -> bool {
        type_id.and_then(|t| self.types.get(t)).and_then(|t| jx::str_(t, "type_kind")) == Some("enum")
    }

    pub fn fqn(&self, type_id: Option<&str>) -> Option<String> {
        type_id.and_then(|t| self.types.get(t)).and_then(|t| jx::str_(t, "fqn")).map(str::to_string)
    }

    /// Метод типа (или суперкласса) по имени и числу параметров.
    pub fn method_of(&self, type_id: Option<&str>, name: &str, arity: Option<usize>) -> Option<String> {
        let tid = type_id.filter(|t| !t.is_empty())?;
        let key = (tid.to_string(), name.to_string(), arity);
        if let Some(r) = self.method_of_cache.borrow().get(&key) {
            return r.clone();
        }
        let mut seen = std::collections::HashSet::new();
        let mut t = Some(tid.to_string());
        let mut res = None;
        'outer: while let Some(cur) = t {
            if !seen.insert(cur.clone()) {
                break;
            }
            if let Some(ms) = self.methods.get(&cur) {
                for mid in ms {
                    let n = &self.nodes[mid];
                    if jx::str_(n, "name") != Some(name) {
                        continue;
                    }
                    if arity.is_none_or(|a| jx::arr(n, "params_as_written").len() == a) {
                        res = Some(mid.clone());
                        break 'outer;
                    }
                }
            }
            t = self.super_of.get(&cur).cloned();
        }
        self.method_of_cache.borrow_mut().insert(key, res.clone());
        res
    }

    /// Константы enum по порядку объявления с литералами аргументов (из исходника по строке поля).
    pub fn enum_constants(&self, type_id: &str) -> Rc<Vec<(String, Vec<Value>)>> {
        if let Some(c) = self.enum_consts.borrow().get(type_id) {
            return c.clone();
        }
        let node = self.types.get(type_id);
        let fqn = node.and_then(|n| jx::str_(n, "fqn")).unwrap_or("");
        let consts: Vec<&Node> = self
            .fields
            .get(type_id)
            .map(|fs| {
                fs.iter()
                    .filter(|f| {
                        let m = jx::strs(f, "modifiers");
                        jx::str_(f, "type") == Some(fqn) && m.contains(&"static") && m.contains(&"final")
                    })
                    .collect()
            })
            .unwrap_or_default();
        let mut text = String::new();
        if let (Some(root), Some(file)) = (&self.targets_root, node.and_then(|n| jx::str_(n, "file")).filter(|f| !f.is_empty())) {
            text = std::fs::read(root.join(file)).map(|b| String::from_utf8_lossy(&b).into_owned()).unwrap_or_default();
        }
        let lines = splitlines(&text);
        let mut out = Vec::new();
        for f in consts {
            let line = jx::int(f, "line").unwrap_or(0);
            let src = if line > 0 && (line as usize) <= lines.len() { lines[line as usize - 1] } else { "" };
            let name = jx::str_(f, "name").unwrap_or("");
            let re = Regex::new(&format!(r"{}\s*\((.*)\)", regex::escape(name))).unwrap();
            let args = re.captures(src).map(|m| parse_java_args(&m[1])).unwrap_or_default();
            out.push((name.to_string(), args));
        }
        let rc = Rc::new(out);
        self.enum_consts.borrow_mut().insert(type_id.to_string(), rc.clone());
        rc
    }
}

/// Преобразование значения колонки-enum в константу: реализует интерпретатор (запускает конструктор enum).
pub type EnumFactory<'a> = &'a mut dyn FnMut(&str, &Value) -> Value;

/// Мир БД сценария: строки <-> объекты, запросы, сохранение.
pub struct World {
    pub db: DatabaseState,
    pub types: Rc<TypeIndex>,
    /// FQN сущности -> таблица.
    pub table_of: IndexMap<String, String>,
    /// FQN сущности -> {поле коллекции: таблица}.
    pub collections_of: IndexMap<String, IndexMap<String, String>>,
    pub id_field: IndexMap<String, String>,
    /// Сохранённые сущности: `(fqn, объект)` — для ссылок `new_of_step_<n>`.
    pub saved: Vec<(String, Shared<Obj>)>,
}

fn is_digit_str(s: &str) -> bool {
    !s.is_empty() && s.chars().all(|c| c.is_ascii_digit())
}

impl World {
    pub fn new(db: DatabaseState, types: Rc<TypeIndex>, raw_entities: &[Json]) -> World {
        let mut table_of = IndexMap::new();
        let mut collections_of = IndexMap::new();
        let mut id_field = IndexMap::new();
        for e in raw_entities {
            let ty = jx::str_(e, "type").unwrap_or("").to_string();
            if let Some(t) = jx::str_(e, "table").filter(|t| !t.is_empty()) {
                table_of.insert(ty.clone(), t.to_string());
            }
            if let Some(i) = jx::str_(e, "id_field").filter(|t| !t.is_empty()) {
                id_field.insert(ty.clone(), i.to_string());
            }
            let colls: IndexMap<String, String> = jx::arr(e, "collections")
                .iter()
                .map(|c| (jx::str_(c, "field").unwrap_or("").to_string(), jx::str_(c, "table").unwrap_or("").to_string()))
                .collect();
            collections_of.insert(ty, colls);
        }
        World { db, types, table_of, collections_of, id_field, saved: Vec::new() }
    }

    // --- строки и объекты ---------------------------------------------------------------------------------------

    pub fn rows(&self, table: &str) -> &[Row] {
        self.db.get_table(table)
    }

    pub fn columns(&self, table: &str) -> Vec<String> {
        let cols = self.db.get_columns(table);
        if !cols.is_empty() {
            return cols;
        }
        self.rows(table).first().map(|r| r.keys().cloned().collect()).unwrap_or_default()
    }

    fn convert(&self, ftype: Option<&str>, raw: &Value, module: Option<&str>, ef: EnumFactory) -> Value {
        if raw.is_null() {
            return Value::Null;
        }
        match ftype {
            Some("int" | "long" | "short" | "java.lang.Integer" | "java.lang.Long") => {
                return match py_float(raw) {
                    Some(f) if f.is_finite() => Value::Int(f as i64),
                    _ => Value::Unknown,
                };
            }
            Some("double" | "float" | "java.lang.Double" | "java.lang.Float" | "java.math.BigDecimal") => {
                return py_float(raw).map(Value::Float).unwrap_or(Value::Unknown);
            }
            Some("boolean" | "java.lang.Boolean") => {
                let s = py_str(raw);
                return Value::Bool(if is_digit_str(&s) { s.parse::<i64>().map(|i| i != 0).unwrap_or(true) } else { s.to_lowercase() == "true" });
            }
            Some("java.lang.String") => return Value::string(py_str(raw)),
            _ => {}
        }
        let tid = self.types.resolve(ftype, module);
        if let Some(t) = tid.as_deref() {
            if self.types.is_enum(Some(t)) {
                return ef(t, raw);
            }
        }
        if ftype.is_some_and(|f| f.starts_with("java.util.Date")) {
            return Value::Unknown;
        }
        raw.clone()
    }

    pub fn row_to_obj(&self, fqn: &str, row: &Row, module: Option<&str>, ef: EnumFactory) -> Shared<Obj> {
        let tid = self.types.resolve(Some(fqn), module);
        let obj = shared(Obj::new(Some(fqn.to_string()), IndexMap::new(), true));
        let colls = self.collections_of.get(fqn);
        for f in self.types.all_fields(tid.as_deref()).iter() {
            let name = jx::str_(f, "name").unwrap_or("");
            let ftype = jx::str_(f, "type");
            let col = column_of(f);
            let v = if let Some(table) = colls.and_then(|c| c.get(name)) {
                Some(self.load_collection(table, row, fqn))
            } else if let Some(raw) = row.get(&col) {
                Some(self.convert(ftype, raw, module, ef))
            } else {
                let sub = self.types.resolve(ftype, module);
                if let Some(s) = sub.as_deref().filter(|s| !self.types.is_enum(Some(s)) && !self.types.all_fields(Some(s)).is_empty()) {
                    let _ = s;
                    Some(Value::Obj(self.row_to_obj(ftype.unwrap_or(""), row, module, ef)))
                } else {
                    None
                }
            };
            if let Some(v) = v {
                obj.borrow_mut().fields.insert(name.to_string(), v);
            }
        }
        obj
    }

    fn load_collection(&self, table: &str, owner_row: &Row, fqn: &str) -> Value {
        let cols = self.columns(table);
        let fk = cols.iter().find(|c| c.ends_with("_id")).cloned();
        let idc = snake(self.id_field.get(fqn).map(String::as_str).unwrap_or("id"));
        let owner_id = match owner_row.get(&idc) {
            Some(v) if py_truthy(v) => Some(v.clone()),
            _ => owner_row.get("id").cloned(),
        };
        let (Some(fk), Some(owner_id)) = (fk, owner_id.filter(|v| !v.is_null())) else {
            return Value::list(Vec::new(), false);
        };
        let mut rows: Vec<&Row> =
            self.rows(table).iter().filter(|r| py_str(r.get(&fk).unwrap_or(&Value::Null)) == py_str(&owner_id)).collect();
        let order = cols.iter().find(|c| c.ends_with("_order")).cloned();
        if let Some(o) = &order {
            let key = |r: &&Row| -> f64 {
                match r.get(o) {
                    Some(v) if py_truthy(v) => py_float(v).unwrap_or(0.0),
                    _ => 0.0,
                }
            };
            rows.sort_by(|a, b| key(a).partial_cmp(&key(b)).unwrap_or(std::cmp::Ordering::Equal));
        }
        let val_cols: Vec<&String> = cols.iter().filter(|c| Some(*c) != Some(&fk) && Some(*c) != order.as_ref()).collect();
        if val_cols.len() == 1 {
            return Value::list(rows.iter().map(|r| r.get(val_cols[0]).cloned().unwrap_or(Value::Null)).collect(), true);
        }
        let items = rows
            .iter()
            .map(|r| {
                let fields: IndexMap<String, Value> =
                    val_cols.iter().map(|c| (camel(c), r.get(*c).cloned().unwrap_or(Value::Null))).collect();
                Value::Obj(shared(Obj::new(None, fields, true)))
            })
            .collect();
        Value::list(items, true)
    }

    pub fn obj_to_row(&self, fqn: &str, obj: &Shared<Obj>, module: Option<&str>) -> Row {
        let tid = self.types.resolve(Some(fqn), module);
        let mut row = Row::new();
        let colls = self.collections_of.get(fqn);
        for f in self.types.all_fields(tid.as_deref()).iter() {
            let name = jx::str_(f, "name").unwrap_or("");
            if colls.is_some_and(|c| c.contains_key(name)) {
                continue;
            }
            let v = obj.borrow().get(name);
            match &v {
                Value::Obj(o) => {
                    let ty = o.borrow().ty.clone().unwrap_or_default();
                    for (k, x) in self.obj_to_row(&ty, o, module) {
                        row.insert(k, x);
                    }
                }
                Value::Enum(e) => {
                    row.insert(column_of(f), e.borrow().ordinal.map(Value::Int).unwrap_or(Value::Null));
                }
                _ => {
                    row.insert(column_of(f), v.clone());
                }
            }
        }
        row
    }

    fn save_collections(&mut self, fqn: &str, obj: &Shared<Obj>, owner_id: &Value) {
        let Some(colls) = self.collections_of.get(fqn).cloned() else { return };
        for (fname, table) in colls {
            let val = obj.borrow().get(&fname);
            let Value::List(l) = val else { continue };
            let cols = self.columns(&table);
            let fk = cols.iter().find(|c| c.ends_with("_id")).cloned();
            let order = cols.iter().find(|c| c.ends_with("_order")).cloned();
            let val_cols: Vec<String> = cols.iter().filter(|c| Some(*c) != fk.as_ref() && Some(*c) != order.as_ref()).cloned().collect();
            let Some(fk) = fk else { continue };
            if let Some(rows) = self.db.table_mut(&table) {
                let oid = py_str(owner_id);
                rows.retain(|r| py_str(r.get(&fk).unwrap_or(&Value::Null)) != oid);
            }
            let items = l.borrow().items.clone();
            for (i, item) in items.into_iter().enumerate() {
                let mut r = Row::new();
                r.insert(fk.clone(), owner_id.clone());
                if let Some(o) = &order {
                    r.insert(o.clone(), Value::Int(i as i64));
                }
                if val_cols.len() == 1 {
                    r.insert(val_cols[0].clone(), item);
                } else if let Value::Obj(o) = &item {
                    for c in &val_cols {
                        r.insert(c.clone(), o.borrow().get(&camel(c)));
                    }
                }
                self.db.insert(&table, r);
            }
        }
    }

    // --- операции репозитория -------------------------------------------------------------------------------------

    /// Колонка и описание поля по имени свойства (`#col:x` — колонка из нативного SQL).
    pub fn field_col(&self, fqn: &str, prop: &str, module: Option<&str>) -> (Option<String>, Option<Node>) {
        if let Some(c) = prop.strip_prefix("#col:") {
            return (Some(c.to_string()), None);
        }
        let tid = self.types.resolve(Some(fqn), module);
        for f in self.types.all_fields(tid.as_deref()).iter() {
            if jx::str_(f, "name").unwrap_or("").to_lowercase() == prop.to_lowercase() {
                return (Some(column_of(f)), Some(f.clone()));
            }
        }
        (Some(snake(prop)), None)
    }

    /// Совпадает ли строка с условием.
    fn match_row(&self, row: &Row, col: Option<&str>, value: &Value, module: Option<&str>) -> Tri {
        if value.is_unknown() {
            return Tri::Unknown;
        }
        if let Value::Obj(o) = value {
            let mut result = Tri::True;
            let ty = o.borrow().ty.clone();
            let sub_tid = self.types.resolve(ty.as_deref(), module);
            for sf in self.types.all_fields(sub_tid.as_deref()).iter() {
                let sc = column_of(sf);
                if !row.contains_key(&sc) {
                    return Tri::Unknown;
                }
                let v = o.borrow().get(jx::str_(sf, "name").unwrap_or(""));
                match self.match_row(row, Some(&sc), &v, module) {
                    Tri::False => return Tri::False,
                    Tri::Unknown => result = Tri::Unknown,
                    Tri::True => {}
                }
            }
            return result;
        }
        let Some(raw) = col.and_then(|c| row.get(c)) else { return Tri::Unknown };
        match value {
            Value::Enum(e) => {
                let e = e.borrow();
                if let Some(i) = raw.as_int_or_bool() {
                    return match e.ordinal {
                        Some(o) => Tri::from_bool(o == i),
                        None => Tri::Unknown,
                    };
                }
                Tri::from_bool(py_str(raw) == e.constant)
            }
            Value::List(l) => {
                let l = l.borrow();
                if !l.exact || l.items.iter().any(Value::is_unknown) {
                    return Tri::Unknown;
                }
                let r = py_str(raw).to_lowercase();
                Tri::from_bool(l.items.iter().any(|x| py_str(x).to_lowercase() == r))
            }
            Value::Bool(b) => Tri::from_bool(py_truthy(raw) == *b),
            Value::Int(_) | Value::Float(_) => {
                let num_or_str = matches!(raw, Value::Int(_) | Value::Float(_) | Value::Bool(_) | Value::Str(_));
                if num_or_str {
                    match (py_float(raw), py_float(value)) {
                        (Some(a), Some(b)) => Tri::from_bool(a == b),
                        _ => Tri::False,
                    }
                } else {
                    Tri::Unknown
                }
            }
            Value::Str(s) => Tri::from_bool(py_str(raw).to_lowercase() == s.to_lowercase()),
            Value::Null => Tri::from_bool(raw.is_null()),
            _ => Tri::Unknown,
        }
    }

    /// Строки сущности под условиями `[(свойство, значение)]`. Возвращает (объекты, точно ли).
    pub fn select(&self, fqn: &str, conds: &[(String, Value)], module: Option<&str>, ef: EnumFactory) -> (Vec<Shared<Obj>>, bool) {
        let Some(table) = self.table_of.get(fqn) else { return (Vec::new(), false) };
        let mut exact = true;
        let mut out = Vec::new();
        let resolved: Vec<_> = conds.iter().map(|(p, v)| (self.field_col(fqn, p, module), v)).collect();
        for row in self.rows(table) {
            let mut ok = Tri::True;
            for ((col, _), v) in &resolved {
                match self.match_row(row, col.as_deref(), v, module) {
                    Tri::False => {
                        ok = Tri::False;
                        break;
                    }
                    Tri::Unknown => ok = Tri::Unknown,
                    Tri::True => {}
                }
            }
            if ok == Tri::False {
                continue;
            }
            if ok == Tri::Unknown {
                exact = false;
            }
            out.push(self.row_to_obj(fqn, row, module, ef));
        }
        (out, exact)
    }

    /// Вставка или обновление по ключу. Возвращает `true`, если строка новая.
    pub fn save(&mut self, fqn: &str, obj: &Value, module: Option<&str>) -> bool {
        let Some(table) = self.table_of.get(fqn).cloned() else { return false };
        let Value::Obj(o) = obj else { return false };
        let id_field = self.id_field.get(fqn).cloned().unwrap_or_else(|| "id".to_string());
        let mut oid = o.borrow().get(&id_field);
        if oid.is_null() {
            oid = Value::string(fresh_uuid());
            o.borrow_mut().fields.insert(id_field.clone(), oid.clone());
        }
        let row = self.obj_to_row(fqn, o, module);
        let (id_col, _) = self.field_col(fqn, &id_field, module);
        if !oid.is_unknown() {
            let want = py_str(&oid);
            let id_col = id_col.clone().unwrap_or_default();
            let mut found = false;
            if let Some(rows) = self.db.table_mut(&table) {
                for r in rows.iter_mut() {
                    if py_str(r.get(&id_col).unwrap_or(&Value::Null)) == want {
                        for (k, v) in &row {
                            if !v.is_unknown() {
                                r.insert(k.clone(), v.clone());
                            }
                        }
                        found = true;
                        break;
                    }
                }
            }
            if found {
                self.save_collections(fqn, o, &oid);
                return false;
            }
        }
        let clean: Row = row.into_iter().filter(|(_, v)| !v.is_unknown()).collect();
        self.db.insert(&table, clean);
        if !oid.is_unknown() {
            self.save_collections(fqn, o, &oid);
        }
        self.saved.push((fqn.to_string(), o.clone()));
        true
    }

    pub fn delete(&mut self, fqn: &str, conds: &[(String, Value)], module: Option<&str>) -> usize {
        let Some(table) = self.table_of.get(fqn).cloned() else { return 0 };
        let resolved: Vec<_> = conds.iter().map(|(p, v)| (self.field_col(fqn, p, module), v.clone())).collect();
        let rows: Vec<Row> = self.rows(&table).to_vec();
        let mut keep = Vec::new();
        let mut n = 0;
        for row in rows {
            if !resolved.is_empty() && resolved.iter().all(|((c, _), v)| self.match_row(&row, c.as_deref(), v, module) == Tri::True) {
                n += 1;
                continue;
            }
            keep.push(row);
        }
        if let Some(t) = self.db.table_mut(&table) {
            *t = keep;
        }
        n
    }
}

// --- разбор имён производных запросов Spring Data -------------------------------------------------------------------

const PREFIXES: [&str; 12] = [
    "findAllBy", "findBy", "getBy", "readBy", "queryBy", "existsBy", "countBy", "deleteAllBy", "deleteBy", "removeBy",
    "findFirstBy", "findTopBy",
];

/// `findByAccountIdAndStatus` -> `("find", ["accountId", "status"])`; `None` — не производный запрос.
pub fn derived_props(name: &str) -> Option<(String, Vec<String>)> {
    thread_local! {
        static ORDER: Regex = Regex::new(r"OrderBy\w+$").unwrap();
        static SUFFIX: Regex = Regex::new(r"(In|IsNull|IsNotNull|Containing|Like)$").unwrap();
    }
    for p in PREFIXES {
        if name.starts_with(p) && name.len() > p.len() {
            let rest = &name[p.len()..];
            let rest = ORDER.with(|re| re.replace(rest, "").into_owned());
            // split по `And(?=[A-Z])`
            let mut parts: Vec<String> = Vec::new();
            let b: Vec<char> = rest.chars().collect();
            let mut cur = String::new();
            let mut i = 0;
            while i < b.len() {
                if b[i..].starts_with(&['A', 'n', 'd']) && b.get(i + 3).is_some_and(|c| c.is_ascii_uppercase()) {
                    parts.push(std::mem::take(&mut cur));
                    i += 3;
                } else {
                    cur.push(b[i]);
                    i += 1;
                }
            }
            parts.push(cur);
            let props: Vec<String> = parts
                .into_iter()
                .filter(|x| !x.is_empty())
                .map(|x| {
                    let mut cs = x.chars();
                    let first = cs.next().map(|c| c.to_lowercase().collect::<String>()).unwrap_or_default();
                    first + cs.as_str()
                })
                .map(|x| SUFFIX.with(|re| re.replace(&x, "").into_owned()))
                .collect();
            let kind = p.replace("By", "").replace("All", "").replace("First", "").replace("Top", "");
            return Some((kind, props));
        }
    }
    None
}

/// `SELECT * FROM t WHERE a = ?1 AND b in ?2` -> `[("a", 0), ("b", 1)]` (колонки, индексы аргументов); `None` — есть `or`.
pub fn native_query_conds(sql: &str) -> Option<Vec<(String, usize)>> {
    thread_local! {
        static WHERE: Regex = Regex::new(r"(?is)\bwhere\b(.*)$").unwrap();
        static COND: Regex = Regex::new(r"(?i)(\w+)\s*(=|in)\s*\?(\d+)").unwrap();
        static OR: Regex = Regex::new(r"(?i)\bor\b").unwrap();
    }
    let Some(where_) = WHERE.with(|re| re.captures(sql).map(|m| m[1].to_string())) else { return Some(Vec::new()) };
    if OR.with(|re| re.is_match(&where_)) {
        return None;
    }
    Some(COND.with(|re| {
        re.captures_iter(&where_).map(|c| (c[1].to_string(), c[3].parse::<usize>().unwrap_or(1).saturating_sub(1))).collect()
    }))
}

/// Optional результата: при неточном условии наличие строки неизвестно, а сама строка — любая (поля `Unknown`).
pub fn optional_of(objs: &[Shared<Obj>], exact: bool, fqn: &str) -> Value {
    if !objs.is_empty() && exact {
        return Value::optional(Value::Obj(objs[0].clone()), false);
    }
    if objs.is_empty() {
        return Value::optional(Value::Null, false);
    }
    if objs.len() == 1 {
        return Value::optional(Value::Obj(objs[0].clone()), true);
    }
    Value::optional(Value::obj(Some(fqn), IndexMap::new(), true), true)
}

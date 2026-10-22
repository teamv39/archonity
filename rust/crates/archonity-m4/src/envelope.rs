//! Обёртка ответа проекта (`engine/executor/envelope.py`): класс, поле статуса, значение успеха.

use std::path::{Path, PathBuf};

use archonity_io::jx;
use archonity_io::SkeletonIndex;
use indexmap::IndexMap;
use regex::Regex;
use serde_json::Value as Json;

use crate::ir::IrStore;

const INT_TYPES: [&str; 6] = ["int", "long", "short", "java.lang.Integer", "java.lang.Long", "java.lang.Short"];
const SKIP_DIR: [&str; 6] = ["node_modules", "target", "build", "dist", ".git", "bower_components"];

#[derive(Clone, Debug)]
pub struct Envelope {
    /// Простое имя класса обёртки.
    pub name: String,
    /// Поле статуса (первый аргумент конструктора).
    pub status: String,
    /// Значение статуса при успехе.
    pub success: i64,
    pub data: Option<String>,
}

fn strip_generics(s: &str) -> String {
    Regex::new(r"<.*>").unwrap().replace_all(s, "").into_owned()
}

impl Envelope {
    /// `edu.x.Response`, `Response<>`, `Response<List<T>>` — тип обёртки.
    pub fn is_type(&self, type_name: Option<&str>) -> bool {
        match type_name.filter(|t| !t.is_empty()) {
            Some(t) => strip_generics(t).rsplit('.').next().unwrap_or("") == self.name,
            None => false,
        }
    }

    pub fn setter(&self) -> String {
        format!("set{}", upper_first(&self.status))
    }

    pub fn getter(&self) -> String {
        format!("get{}", upper_first(&self.status))
    }

    /// `lit != success` для литерала IR.
    pub fn lit_is_failure(&self, lit: &Json) -> bool {
        match lit.as_f64() {
            Some(f) if lit.is_number() => f != self.success as f64,
            _ => true,
        }
    }
}

pub fn upper_first(s: &str) -> String {
    let mut cs = s.chars();
    match cs.next() {
        Some(f) => f.to_uppercase().collect::<String>() + cs.as_str(),
        None => String::new(),
    }
}

/// Все словари в обходе в глубину, в порядке документа (`_walk`).
pub fn walk<'a>(x: &'a Json, out: &mut Vec<&'a Json>) {
    match x {
        Json::Object(o) => {
            out.push(x);
            for v in o.values() {
                walk(v, out);
            }
        }
        Json::Array(a) => {
            for v in a {
                walk(v, out);
            }
        }
        _ => {}
    }
}

/// `new X(<целое>, "<строка>", ...)`, в т.ч. последним аргументом вызова -> простое имя X.
fn status_ctor(e: &Json) -> Option<String> {
    if !e.is_object() {
        return None;
    }
    if let Some(new) = jx::get(e, "new") {
        let a = jx::arr(e, "args");
        let lit_int = |x: &Json| jx::get(x, "lit").is_some_and(|l| l.is_i64() || l.is_u64());
        let lit_str = |x: &Json| jx::get(x, "lit").is_some_and(Json::is_string);
        if a.len() >= 2 && a[0].is_object() && lit_int(&a[0]) && a[1].is_object() && lit_str(&a[1]) {
            return Some(strip_generics(new.as_str().unwrap_or("")).rsplit('.').next().unwrap_or("").to_string());
        }
        return None;
    }
    if jx::get(e, "call").is_some() {
        if let Some(last) = jx::arr(e, "args").last() {
            return status_ctor(last);
        }
    }
    None
}

#[derive(Default)]
struct Counter(IndexMap<i64, usize>);

fn is_vendor(name: &str) -> bool {
    thread_local! {
        // Сборки `.min.` и общеизвестные фреймворки (`VENDOR`, ui_catalog.py)
        static V: Regex =
            Regex::new(r"(?i)(\.min\.|^(vue|angular|jquery|bootstrap|echarts|react|lodash|moment|d3|three|npm)\b)").unwrap();
    }
    V.with(|re| re.is_match(name))
}

/// Файлы интерфейса: `.js`, `.html`, `.htm` без вендорных и крупнее 400 КБ, как `os.walk` с сортировкой.
pub fn ui_files(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    fn go(dir: &Path, out: &mut Vec<PathBuf>) {
        let Ok(rd) = std::fs::read_dir(dir) else { return };
        let mut dirs = Vec::new();
        let mut files = Vec::new();
        for e in rd.flatten() {
            let name = e.file_name().to_string_lossy().into_owned();
            let is_dir = e.file_type().map(|t| t.is_dir()).unwrap_or(false);
            if is_dir {
                dirs.push(name);
            } else {
                files.push(name);
            }
        }
        dirs.retain(|d| !SKIP_DIR.contains(&d.as_str()) && !d.starts_with('.'));
        dirs.sort();
        files.sort();
        for f in files {
            if (f.ends_with(".js") || f.ends_with(".html") || f.ends_with(".htm")) && !is_vendor(&f) {
                let p = dir.join(&f);
                if std::fs::metadata(&p).map(|m| m.len() < 400_000).unwrap_or(false) {
                    out.push(p);
                }
            }
        }
        for d in dirs {
            go(&dir.join(d), out);
        }
    }
    go(root, &mut out);
    out
}

/// Модуль веб-интерфейса: каталог верхнего уровня, который не модуль Java скелета, с наибольшим числом HTML-страниц.
pub fn find_ui_dir(targets_root: &Path, ix: &SkeletonIndex) -> Option<String> {
    let java: std::collections::HashSet<&str> =
        ix.n.values().filter_map(|n| jx::str_(n, "module")).filter(|m| !m.is_empty()).collect();
    let mut dirs: Vec<String> = std::fs::read_dir(targets_root)
        .ok()?
        .flatten()
        .filter(|e| e.file_type().map(|t| t.is_dir()).unwrap_or(false))
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| !java.contains(n.as_str()) && !n.starts_with('.'))
        .collect();
    dirs.sort();
    let mut best: Option<(usize, String)> = None;
    for d in dirs {
        let pages = ui_files(&targets_root.join(&d))
            .iter()
            .filter(|f| f.extension().is_some_and(|e| e == "html" || e == "htm"))
            .count();
        if pages > 0 && best.as_ref().is_none_or(|b| pages > b.0) {
            best = Some((pages, d));
        }
    }
    best.map(|b| b.1)
}

/// Литералы, с которыми UI сравнивает `<ответ>.<статус>`.
fn ui_success(status: &str, targets_root: Option<&Path>, ix: &SkeletonIndex) -> Counter {
    let mut out = Counter::default();
    let Some(root) = targets_root else { return out };
    let Some(ui_dir) = find_ui_dir(root, ix) else { return out };
    let pat = Regex::new(&format!(r"\.{}\s*===?\s*(-?\d+)\b", regex::escape(status))).unwrap();
    for p in ui_files(&root.join(ui_dir)) {
        if p.extension().is_some_and(|e| e == "js") {
            let text = std::fs::read(&p).map(|b| String::from_utf8_lossy(&b).into_owned()).unwrap_or_default();
            for m in pat.captures_iter(&text) {
                if let Ok(v) = m[1].parse::<i64>() {
                    *out.0.entry(v).or_insert(0) += 1;
                }
            }
        }
    }
    out
}

/// Литералы в сравнениях `x.<getter>() == / != <литерал>` сервисов проекта.
fn java_success(getter: &str, ir: &IrStore) -> Counter {
    let mut out = Counter::default();
    for m in ir.values() {
        let mut ds = Vec::new();
        if let Some(b) = jx::get(m, "body") {
            walk(b, &mut ds);
        }
        for e in ds {
            if matches!(jx::str_(e, "bin"), Some("==" | "!=")) {
                let l_ok = jx::get(e, "l").is_some_and(|l| jx::str_(l, "callee") == Some(getter));
                let lit = jx::get(e, "r").and_then(|r| jx::get(r, "lit")).and_then(|l| l.as_i64().filter(|_| l.is_i64()));
                if let (true, Some(v)) = (l_ok, lit) {
                    *out.0.entry(v).or_insert(0) += 1;
                }
            }
        }
    }
    out
}

/// Соглашение об ответе по IR, скелету и UI; `None` — в проекте его не видно.
pub fn derive(ix: &SkeletonIndex, ir: &IrStore, targets_root: Option<&Path>) -> Option<Envelope> {
    let mut ctors: IndexMap<String, usize> = IndexMap::new();
    for m in ir.values() {
        let mut ds = Vec::new();
        if let Some(b) = jx::get(m, "body") {
            walk(b, &mut ds);
        }
        for s in ds {
            if jx::str_(s, "op") == Some("return") {
                if let Some(x) = jx::get(s, "expr").and_then(status_ctor) {
                    *ctors.entry(x).or_insert(0) += 1;
                }
            }
        }
    }
    if ctors.is_empty() {
        return None;
    }
    // most_common(1): первый из максимальных по порядку вставки
    let (name, _) = ctors.iter().fold(None::<(&String, &usize)>, |best, (k, v)| match best {
        Some((_, bv)) if bv >= v => best,
        _ => Some((k, v)),
    })?;
    let name = name.clone();
    let nodes = &ix.n;
    let mut types: Vec<(&String, &Json)> = nodes
        .iter()
        .filter(|(_, n)| jx::str_(n, "kind") == Some("type") && jx::str_(n, "fqn").unwrap_or("").rsplit('.').next() == Some(name.as_str()))
        .collect();
    types.sort_by(|a, b| a.0.cmp(b.0));
    let mut status = None;
    let mut data = None;
    for (tid, t) in types {
        let fields: Vec<&Json> =
            nodes.values().filter(|n| jx::str_(n, "kind") == Some("field") && jx::str_(n, "owner") == Some(tid.as_str())).collect();
        let ints: Vec<&str> = fields
            .iter()
            .filter(|f| jx::str_(f, "type").is_some_and(|t| INT_TYPES.contains(&t)))
            .filter_map(|f| jx::str_(f, "name"))
            .collect();
        let params: Vec<&str> = jx::strs(t, "type_params");
        let generic: Vec<&str> = fields
            .iter()
            .filter(|f| jx::str_(f, "type_raw").is_some_and(|t| params.contains(&t)))
            .filter_map(|f| jx::str_(f, "name"))
            .collect();
        if ints.len() == 1 {
            status = Some(ints[0].to_string());
            data = if generic.len() == 1 { Some(generic[0].to_string()) } else { None };
            break;
        }
    }
    let status = status?;
    let ui = ui_success(&status, targets_root, ix);
    let votes = if !ui.0.is_empty() { ui } else { java_success(&format!("get{}", upper_first(&status)), ir) };
    // most_common(2): по убыванию счёта, при равенстве — порядок вставки
    let mut top: Vec<(i64, usize)> = votes.0.iter().map(|(k, v)| (*k, *v)).collect();
    top.sort_by(|a, b| b.1.cmp(&a.1));
    top.truncate(2);
    if top.is_empty() || (top.len() > 1 && top[0].1 == top[1].1) {
        return None;
    }
    Some(Envelope { name, status, success: top[0].0, data })
}

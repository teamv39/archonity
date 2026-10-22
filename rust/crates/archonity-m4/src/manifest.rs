//! Манифест сущностей (`engine/manifest.py`): виды, ID-поля, таблицы по аннотациям скелета.

use std::collections::BTreeMap;

use archonity_io::jx;
use archonity_io::skeleton::Node;
use archonity_io::SkeletonIndex;
use archonity_model::names::{camel_to_snake, simple_name};
use indexmap::IndexMap;
use regex::Regex;

const ENTITY_ANNOTATIONS: [&str; 2] = ["Entity", "Embeddable"];
const ID_ANNOTATIONS: [&str; 2] = ["Id", "EmbeddedId"];

#[derive(Clone, Debug)]
pub struct EntityKind {
    /// `trainType`.
    pub kind: String,
    /// FQN классов с этим простым именем.
    pub types: Vec<String>,
    /// `@Id` (если не `id`), `<вид>Id`, `id`.
    pub id_fields: Vec<String>,
    /// ID узлов таблиц из `@Table` или имени класса.
    pub tables: Vec<String>,
}

/// Вид по простому имени класса: первая буква строчная.
pub fn kind_name(simple: &str) -> String {
    let mut cs = simple.chars();
    match cs.next() {
        Some(f) => f.to_lowercase().collect::<String>() + cs.as_str(),
        None => String::new(),
    }
}

/// Аннотация узла по имени; элемент-строка — аннотация без аргументов.
fn annotation(n: &Node, names: &[&str]) -> Option<(String, String)> {
    for a in jx::arr(n, "annotations") {
        let (name, args) = match a {
            serde_json::Value::Object(_) => (jx::str_(a, "name").unwrap_or("").to_string(), jx::str_(a, "args").unwrap_or("").to_string()),
            serde_json::Value::String(s) => (s.clone(), String::new()),
            _ => continue,
        };
        if names.contains(&name.as_str()) {
            return Some((name, args));
        }
    }
    None
}

fn fqn_of(nid: &str, n: &Node) -> String {
    match jx::str_(n, "fqn").filter(|f| !f.is_empty()) {
        Some(f) => f.to_string(),
        None => nid.splitn(3, ':').last().unwrap_or("").to_string(),
    }
}

/// Строковый аргумент аннотации верхнего уровня: `name` в `@Table(name = "x", indexes = {@Index(name = ..)})`.
fn ann_arg(a: &Option<(String, String)>, key: &str) -> Option<String> {
    let (_, args0) = a.as_ref()?;
    let nested = Regex::new(r"\{[^{}]*\}|@\w+\([^()]*\)").unwrap();
    let mut args = args0.clone();
    loop {
        let next = nested.replace_all(&args, "").into_owned();
        if next == args {
            break;
        }
        args = next;
    }
    let re = Regex::new(&format!(r#"\b{}\s*=\s*"([^"]*)""#, regex::escape(key))).unwrap();
    re.captures(&args).map(|m| m[1].to_string()).filter(|s| !s.is_empty())
}

/// Узел таблицы сущности: `res:table:<схема>.<имя>`.
fn table_of(nid: &str, n: &Node) -> String {
    let table = annotation(n, &["Table"]);
    let name = ann_arg(&table, "name")
        .or_else(|| ann_arg(&annotation(n, &["Entity"]), "name"))
        .unwrap_or_else(|| camel_to_snake(&simple_name(Some(&fqn_of(nid, n)), false)));
    let schema = ann_arg(&table, "schema").unwrap_or_else(|| jx::str_(n, "module").unwrap_or("").to_string());
    format!("res:table:{schema}.{name}")
}

/// Виды сущностей проекта по аннотациям узлов скелета, по имени вида.
pub fn entity_kinds(ix: &SkeletonIndex) -> IndexMap<String, EntityKind> {
    let nodes = &ix.n;
    let types: BTreeMap<&String, &Node> = nodes
        .iter()
        .filter(|(_, n)| jx::str_(n, "kind") == Some("type") && annotation(n, &ENTITY_ANNOTATIONS).is_some())
        .collect();
    let mut ids: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    for n in nodes.values() {
        if jx::str_(n, "kind") == Some("field") {
            if let Some(owner) = jx::str_(n, "owner").filter(|o| types.contains_key(&o.to_string())) {
                if annotation(n, &ID_ANNOTATIONS).is_some() {
                    ids.entry(owner).or_default().push(jx::str_(n, "name").unwrap_or("").to_string());
                }
            }
        }
    }
    let mut by_kind: BTreeMap<String, Vec<&String>> = BTreeMap::new();
    for (nid, n) in &types {
        by_kind.entry(kind_name(&simple_name(Some(&fqn_of(nid, n)), false))).or_default().push(nid);
    }
    let mut out = IndexMap::new();
    for (kind, tids) in by_kind {
        let mut own: Vec<String> = tids
            .iter()
            .flat_map(|t| ids.get(t.as_str()).cloned().unwrap_or_default())
            .filter(|f| !f.is_empty() && f != "id")
            .collect();
        own.sort();
        own.dedup();
        let mut tables: Vec<String> = tids.iter().map(|nid| table_of(nid, types[*nid])).filter(|t| nodes.contains_key(t)).collect();
        tables.sort();
        tables.dedup();
        let mut tys: Vec<String> = tids.iter().map(|t| fqn_of(t, types[*t])).collect();
        tys.sort();
        let mut id_fields: Vec<String> = Vec::new();
        for f in own.into_iter().chain([format!("{kind}Id"), "id".to_string()]) {
            if !id_fields.contains(&f) {
                id_fields.push(f);
            }
        }
        out.insert(kind.clone(), EntityKind { kind, types: tys, id_fields, tables });
    }
    out
}

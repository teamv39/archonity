//! Факты archparse о сущностях (`engine/entities.py`, `data/entity_ir.json`), привязанные к скелету.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use indexmap::IndexMap;
use serde_json::Value as Json;

use crate::jx;

#[derive(Clone, Debug)]
pub struct Entity {
    pub ty: String,
    pub module: String,
    pub table: Option<String>,
    pub id_field: Option<String>,
    pub no_arg_ctor: Option<String>,
    pub ctor_statements: i64,
    pub embedded: Vec<String>,
    /// Коллекции в отдельных таблицах: таблица -> (поле, `LAZY` | `EAGER`).
    pub collections: IndexMap<String, (String, String)>,
}

#[derive(Clone, Debug)]
pub struct RepositoryCall {
    pub method: String,
    pub line: i64,
    pub col: i64,
    pub callee: String,
    pub operation: String,
    pub expects: Option<String>,
    pub expects_reason: Option<String>,
    pub id_assigned: Option<bool>,
    pub id_assigned_reason: Option<String>,
    pub entity: Option<Entity>,
    pub tables: BTreeSet<String>,
    pub main_table: Option<String>,
    pub ctors: Vec<String>,
    /// Таблицы ленивых коллекций среди `tables`: ID узла таблицы -> поле.
    pub lazy_tables: IndexMap<String, String>,
    /// Для READ: поля ленивых коллекций, которые метод загрузил сам (`None` — archparse не определил).
    pub collections_loaded: Option<Vec<String>>,
    pub collections_loaded_reason: Vec<String>,
    /// `(метод сущности, вызов библиотеки)`.
    pub element_callbacks: Vec<(String, String)>,
}

#[derive(Clone, Debug, Default)]
pub struct EntityFacts {
    raw_entities: Vec<Json>,
    raw_calls: Vec<Json>,
    constructors: Vec<Json>,
    ctor_statements: IndexMap<String, i64>,
    pub entities: IndexMap<String, Entity>,
    pub calls_by_method: IndexMap<String, Vec<RepositoryCall>>,
    /// Конструкторы с вызовом проектного метода в теле.
    pub ctors_with_project_calls: BTreeSet<String>,
}

fn opt_string(v: &Json, key: &str) -> Option<String> {
    jx::str_(v, key).map(str::to_string)
}

impl EntityFacts {
    /// Сырые описания сущностей из `entity_ir.json` (для мира БД).
    pub fn raw_entities(&self) -> &[Json] {
        &self.raw_entities
    }

    /// Нет файла или он не читается — пустые факты (правило загрузки сущностей выключено), как в Python.
    pub fn load(path: &Path) -> EntityFacts {
        let data: Option<Json> = std::fs::read_to_string(path).ok().and_then(|t| serde_json::from_str(&t).ok());
        match data {
            Some(d) => EntityFacts::from_json(&d),
            None => {
                eprintln!("Не удалось загрузить entity_ir.json, правило загрузки сущностей выключено: {}", path.display());
                EntityFacts::default()
            }
        }
    }

    pub fn from_json(d: &Json) -> EntityFacts {
        let list = |k: &str| jx::arr(d, k).to_vec();
        let mut ctor_statements = IndexMap::new();
        if let Some(o) = jx::get(d, "no_arg_ctor_statements").and_then(Json::as_object) {
            for (k, v) in o {
                ctor_statements.insert(k.clone(), v.as_i64().unwrap_or(0));
            }
        }
        EntityFacts {
            raw_entities: list("entities"),
            raw_calls: list("repository_calls"),
            constructors: list("constructors"),
            ctor_statements,
            ..EntityFacts::default()
        }
    }

    /// Привязка к скелету: call_site по `(file, line, col)`, таблицы `data_access`, ID конструкторов.
    pub fn bind(&mut self, nodes: &IndexMap<String, Json>, edges: &[Json]) {
        let mut cs_by_pos: BTreeMap<(String, i64, i64), String> = BTreeMap::new();
        for (nid, n) in nodes {
            if jx::str_(n, "kind") == Some("call_site") {
                cs_by_pos.insert(
                    (jx::str_(n, "file").unwrap_or("").to_string(), jx::int(n, "line").unwrap_or(0), jx::int(n, "col").unwrap_or(0)),
                    nid.clone(),
                );
            }
        }
        let mut tables_by_cs: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        let mut calls_from_cs: BTreeSet<String> = BTreeSet::new();
        for e in edges {
            let (src, tgt) = (jx::str_(e, "source").unwrap_or(""), jx::str_(e, "target").unwrap_or(""));
            match jx::str_(e, "type") {
                Some("data_access") => {
                    tables_by_cs.entry(src.to_string()).or_default().insert(tgt.to_string());
                }
                Some("calls") => {
                    calls_from_cs.insert(src.to_string());
                }
                _ => {}
            }
        }

        let mut with_calls = BTreeSet::new();
        for ir in &self.constructors {
            for c in jx::arr(ir, "calls") {
                let pos = (jx::str_(c, "file").unwrap_or("").to_string(), jx::int(c, "line").unwrap_or(0), jx::int(c, "col").unwrap_or(0));
                let cs = cs_by_pos.get(&pos);
                if jx::str_(c, "kind") == Some("ENUM") || cs.is_some_and(|cs| calls_from_cs.contains(cs)) {
                    with_calls.insert(jx::str_(ir, "method_id").unwrap_or("").to_string());
                    break;
                }
            }
        }
        self.ctors_with_project_calls = with_calls;

        for d in &self.raw_entities {
            let ty = jx::str_(d, "type").unwrap_or("").to_string();
            let ctor = opt_string(d, "no_arg_ctor").filter(|c| nodes.contains_key(c));
            let mut collections = IndexMap::new();
            for c in jx::arr(d, "collections") {
                collections.insert(
                    jx::str_(c, "table").unwrap_or("").to_string(),
                    (jx::str_(c, "field").unwrap_or("").to_string(), jx::str_(c, "fetch").unwrap_or("LAZY").to_string()),
                );
            }
            self.entities.insert(
                ty.clone(),
                Entity {
                    ty,
                    module: jx::str_(d, "module").unwrap_or("").to_string(),
                    table: opt_string(d, "table"),
                    id_field: opt_string(d, "id_field"),
                    no_arg_ctor: ctor,
                    ctor_statements: jx::int(d, "ctor_statements").unwrap_or(0),
                    embedded: jx::strs(d, "embedded").into_iter().map(str::to_string).collect(),
                    collections,
                },
            );
        }

        let mut unmatched = 0;
        for d in &self.raw_calls {
            let pos = (jx::str_(d, "file").unwrap_or("").to_string(), jx::int(d, "line").unwrap_or(0), jx::int(d, "col").unwrap_or(0));
            let Some(cs) = cs_by_pos.get(&pos) else {
                unmatched += 1;
                continue;
            };
            let method = jx::str_(&nodes[cs], "method").unwrap_or("").to_string();
            let tables = tables_by_cs.get(cs).cloned().unwrap_or_default();
            let entity = jx::str_(d, "entity").and_then(|e| self.entities.get(e)).cloned();
            let mut main_table = None;
            let mut lazy_tables = IndexMap::new();
            if let Some(ent) = &entity {
                if let Some(tn) = &ent.table {
                    main_table = tables.iter().find(|t| nodes.get(*t).and_then(|n| jx::str_(n, "name")) == Some(tn.as_str())).cloned();
                }
                for t in &tables {
                    let name = nodes.get(t).and_then(|n| jx::str_(n, "name")).unwrap_or("");
                    if let Some((field, fetch)) = ent.collections.get(name) {
                        if fetch == "LAZY" {
                            lazy_tables.insert(t.clone(), field.clone());
                        }
                    }
                }
            }
            let loaded = match jx::get(d, "collections_loaded") {
                Some(Json::Array(a)) => Some(a.iter().filter_map(|x| x.as_str().map(str::to_string)).collect()),
                _ => None,
            };
            let ctors = Self::ctors_of(&self.ctor_statements, entity.as_ref(), nodes);
            let call = RepositoryCall {
                method: method.clone(),
                line: jx::int(d, "line").unwrap_or(0),
                col: jx::int(d, "col").unwrap_or(0),
                callee: jx::str_(d, "callee").unwrap_or("").to_string(),
                operation: jx::str_(d, "operation").unwrap_or("READ").to_string(),
                expects: opt_string(d, "expects"),
                expects_reason: opt_string(d, "expects_reason"),
                id_assigned: jx::get(d, "id_assigned").and_then(Json::as_bool),
                id_assigned_reason: opt_string(d, "id_assigned_reason"),
                entity,
                tables,
                main_table,
                ctors,
                lazy_tables,
                collections_loaded: loaded,
                collections_loaded_reason: jx::strs(d, "collections_loaded_reason").into_iter().map(str::to_string).collect(),
                element_callbacks: jx::arr(d, "element_callbacks")
                    .iter()
                    .filter(|cb| jx::str_(cb, "method").is_some_and(|m| nodes.contains_key(m)))
                    .map(|cb| (jx::str_(cb, "method").unwrap().to_string(), jx::str_(cb, "via").unwrap_or("").to_string()))
                    .collect(),
            };
            self.calls_by_method.entry(method).or_default().push(call);
        }
        if unmatched > 0 {
            eprintln!("entity_ir.json: {unmatched} вызовов репозиториев без call_site в скелете");
        }
    }

    /// Ушёл ли SQL к таблице ленивой коллекции, пока метод на стеке (R10). `None` — решение не наше.
    pub fn collection_table_loaded(&self, method: &str, table: &str) -> Option<(bool, String)> {
        let calls: Vec<&RepositoryCall> =
            self.calls_by_method.get(method).map(|v| v.iter().filter(|c| c.tables.contains(table)).collect()).unwrap_or_default();
        if calls.is_empty() || !calls.iter().any(|c| c.lazy_tables.contains_key(table)) {
            return None;
        }
        for c in &calls {
            let Some(coll) = c.lazy_tables.get(table) else {
                return Some((true, format!("R10:not_lazy_at_line_{}", c.line)));
            };
            if c.operation != "READ" {
                return Some((true, format!("R10:{}_writes_collection(line {})", c.operation.to_lowercase(), c.line)));
            }
            let Some(loaded) = &c.collections_loaded else {
                return Some((true, format!("R10:loaded_unknown(line {})", c.line)));
            };
            if loaded.contains(coll) {
                let mut chars = coll.chars();
                let cap: String = chars.next().map(|f| f.to_uppercase().collect::<String>() + chars.as_str()).unwrap_or_default();
                let needle = format!(".get{cap}()");
                let why = c.collections_loaded_reason.iter().find(|r| r.contains(&needle)).cloned().unwrap_or_default();
                return Some((true, format!("R10:loaded({why})")));
            }
        }
        let lines = calls.iter().map(|c| c.line.to_string()).collect::<Vec<_>>().join(",");
        Some((false, format!("R10:lazy_not_loaded(lines {lines})")))
    }

    /// Конструкторы, которые исполняются при загрузке в режиме `constructors`: `None` — все с непустым телом.
    pub fn allowed_ctors(&self, mode: &str) -> Option<BTreeSet<String>> {
        match mode {
            "all" => Some(self.ctors_with_project_calls.clone()),
            "off" => Some(BTreeSet::new()),
            _ => None,
        }
    }

    fn ctors_of(statements: &IndexMap<String, i64>, entity: Option<&Entity>, nodes: &IndexMap<String, Json>) -> Vec<String> {
        let Some(e) = entity else { return Vec::new() };
        let mut out = Vec::new();
        if let Some(c) = &e.no_arg_ctor {
            if e.ctor_statements > 0 {
                out.push(c.clone());
            }
        }
        for emb in &e.embedded {
            let suffix = format!(":{emb}#<init>()");
            for (mid, n) in statements {
                if mid.ends_with(&suffix) && *n > 0 && nodes.contains_key(mid) {
                    out.push(mid.clone());
                }
            }
        }
        out
    }
}

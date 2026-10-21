//! Индекс скелета (`engine/adapters/skeleton.py::SkeletonIndex`). Порядок вставки значим: `IndexMap`.

use std::collections::{BTreeMap, BTreeSet};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use anyhow::{Context, Result};
use flate2::read::GzDecoder;
use indexmap::IndexMap;
use regex::Regex;
use serde_json::Value as Json;

use crate::db::{load_db_dump, parse_context, DatabaseState};
use crate::entities::EntityFacts;
use crate::jx;

/// Узел скелета как есть (`kind`, `owner`, `module`, `annotations`, …).
pub type Node = Json;

pub const DB_DUMP_NAME: &str = "db-after-warmup.sql.gz";

pub struct SkeletonIndex {
    pub project: String,
    /// Узлы по ID, в порядке файла.
    pub n: Rc<IndexMap<String, Node>>,
    pub edges: Rc<Vec<Json>>,
    pub table_nodes: IndexMap<String, Node>,
    pub db_state: DatabaseState,
    /// Поле `context` скелета как есть.
    pub raw_context: Json,
    /// Поле `context` скелета, разобранное `parse_context`.
    pub context: IndexMap<String, Json>,
    /// `(ID метода, глагол, сегменты пути)`.
    pub handlers: Vec<(String, Option<String>, Vec<String>)>,
    pub cs_nodes_by_method: IndexMap<String, Vec<Node>>,
    pub type_nodes: IndexMap<String, Node>,
    pub methods_by_owner: IndexMap<String, Vec<(String, Node)>>,
    pub entities: EntityFacts,
    /// Рёбра `calls`: метод -> цели (call_site приведён к методу).
    pub calls: IndexMap<String, BTreeSet<String>>,
    /// Рёбра `overrides`: переопределённый метод -> переопределяющие.
    pub over: IndexMap<String, BTreeSet<String>>,
    /// `remote_call`, `message_delivery`, `runtime_dispatch`, `data_access`: метод -> цели.
    pub wiring: IndexMap<String, IndexMap<String, BTreeSet<String>>>,
    /// Метод -> модуль.
    pub module: IndexMap<String, Option<String>>,
    pub units: IndexMap<String, BTreeSet<String>>,
    pub size: BTreeMap<String, usize>,
}

/// Дамп БД пакета задачи рядом со скелетом (`<пакет>/skeleton/x` -> `<пакет>/context/<дамп>`).
pub fn default_db_dump(skeleton_path: &Path) -> Option<PathBuf> {
    let p = std::fs::canonicalize(skeleton_path).ok()?.parent()?.parent()?.join("context").join(DB_DUMP_NAME);
    p.is_file().then_some(p)
}

pub fn load_json(path: &Path) -> Result<Json> {
    let raw = std::fs::read(path).with_context(|| format!("не прочитан {}", path.display()))?;
    if path.extension().is_some_and(|e| e == "gz") {
        let mut text = Vec::new();
        GzDecoder::new(&raw[..]).read_to_end(&mut text)?;
        Ok(serde_json::from_slice(&text)?)
    } else {
        Ok(serde_json::from_slice(&raw)?)
    }
}

/// Сегменты пути без query и пустых частей.
pub fn path_segs(p: &str) -> Vec<String> {
    p.split('?').next().unwrap_or("").split('/').filter(|s| !s.is_empty()).map(str::to_string).collect()
}

/// `(глагол, значения путей)` из аннотаций `*Mapping`.
pub fn ann_paths(anns: &[Json]) -> Vec<(Option<String>, Vec<String>)> {
    let quoted = Regex::new(r#""([^"]*)""#).unwrap();
    let mut out = Vec::new();
    for a in anns {
        let name = jx::str_(a, "name").unwrap_or("");
        if name.ends_with("Mapping") {
            let args = jx::str_(a, "args").unwrap_or("");
            let mut vals: Vec<String> = quoted.captures_iter(args).map(|c| c[1].to_string()).collect();
            let verb = name.replace("Mapping", "").to_uppercase();
            if vals.is_empty() {
                vals = vec![String::new()];
            }
            out.push((if verb == "REQUEST" { None } else { Some(verb) }, vals));
        }
    }
    out
}

impl SkeletonIndex {
    /// `skeleton_path` — `.json.gz`; дамп БД ищется рядом (`default_db_dump`), если `db_dump` не задан.
    pub fn load(skeleton_path: &Path, db_dump: Option<&Path>, entity_ir: &Path) -> Result<SkeletonIndex> {
        let sk = load_json(skeleton_path)?;
        let dump = db_dump.map(Path::to_path_buf).or_else(|| default_db_dump(skeleton_path));
        let entities = EntityFacts::load(entity_ir);
        Ok(Self::from_json(&sk, dump.as_deref(), entities))
    }

    pub fn from_json(sk: &Json, db_dump: Option<&Path>, entities: EntityFacts) -> SkeletonIndex {
        let project = jx::str_(sk, "project").unwrap_or("").to_string();
        let n: IndexMap<String, Node> =
            jx::get(sk, "nodes").and_then(Json::as_object).map(|o| o.iter().map(|(k, v)| (k.clone(), v.clone())).collect()).unwrap_or_default();
        let edges: Vec<Json> = jx::arr(sk, "edges").to_vec();

        let table_nodes: IndexMap<String, Node> =
            n.iter().filter(|(id, _)| id.starts_with("res:table:")).map(|(k, v)| (k.clone(), v.clone())).collect();

        let db_state = match db_dump {
            Some(p) => load_db_dump(p).unwrap_or_default(),
            None => DatabaseState::default(),
        };

        let ctx_text = match jx::get(sk, "context") {
            Some(Json::Object(o)) => o.values().map(jx::py_str).collect::<Vec<_>>().join(" "),
            Some(Json::Null) | None => String::new(),
            Some(other) => jx::py_str(other),
        };
        let context = parse_context(&ctx_text);

        let mut handlers = Vec::new();
        for (nid, node) in &n {
            if jx::str_(node, "kind") != Some("method") {
                continue;
            }
            let mp = ann_paths(jx::arr(node, "annotations"));
            if mp.is_empty() {
                continue;
            }
            let owner = jx::str_(node, "owner").unwrap_or("");
            let mut cls_paths: Vec<String> = n
                .get(owner)
                .map(|o| ann_paths(jx::arr(o, "annotations")).into_iter().flat_map(|(_, vals)| vals).collect())
                .unwrap_or_default();
            if cls_paths.is_empty() {
                cls_paths = vec![String::new()];
            }
            for (verb, vals) in &mp {
                for v in vals {
                    for cp in &cls_paths {
                        handlers.push((nid.clone(), verb.clone(), path_segs(&format!("{cp}/{v}"))));
                    }
                }
            }
        }

        let mut cs_method: BTreeMap<&str, &str> = BTreeMap::new();
        let mut cs_nodes_by_method: IndexMap<String, Vec<Node>> = IndexMap::new();
        let mut type_nodes = IndexMap::new();
        let mut methods_by_owner: IndexMap<String, Vec<(String, Node)>> = IndexMap::new();
        for (nid, node) in &n {
            match jx::str_(node, "kind") {
                Some("call_site") => {
                    if let Some(m) = jx::str_(node, "method").filter(|m| !m.is_empty()) {
                        cs_method.insert(nid, m);
                        cs_nodes_by_method.entry(m.to_string()).or_default().push(node.clone());
                    }
                }
                Some("type") => {
                    type_nodes.insert(nid.clone(), node.clone());
                }
                Some("method") => {
                    if let Some(owner) = jx::str_(node, "owner").filter(|o| !o.is_empty()) {
                        methods_by_owner.entry(owner.to_string()).or_default().push((nid.clone(), node.clone()));
                    }
                }
                _ => {}
            }
        }

        let mut calls: IndexMap<String, BTreeSet<String>> = IndexMap::new();
        let mut over: IndexMap<String, BTreeSet<String>> = IndexMap::new();
        let mut wiring: IndexMap<String, IndexMap<String, BTreeSet<String>>> = IndexMap::new();
        for e in &edges {
            let etype = jx::str_(e, "type").unwrap_or("");
            let src = jx::str_(e, "source").unwrap_or("");
            let tgt = jx::str_(e, "target").unwrap_or("");
            let src_m = cs_method.get(src).copied().unwrap_or(src);
            match etype {
                "calls" => {
                    calls.entry(src_m.to_string()).or_default().insert(tgt.to_string());
                }
                "overrides" => {
                    over.entry(tgt.to_string()).or_default().insert(src.to_string());
                }
                "remote_call" | "message_delivery" | "runtime_dispatch" | "data_access" => {
                    wiring.entry(etype.to_string()).or_default().entry(src_m.to_string()).or_default().insert(tgt.to_string());
                }
                _ => {}
            }
        }

        let mut entities = entities;
        entities.bind(&n, &edges);
        let (n, edges) = (Rc::new(n), Rc::new(edges));

        let module: IndexMap<String, Option<String>> = n
            .iter()
            .filter(|(_, v)| jx::str_(v, "kind") == Some("method"))
            .map(|(k, v)| (k.clone(), jx::str_(v, "module").map(str::to_string)))
            .collect();
        let mut units: IndexMap<String, BTreeSet<String>> = IndexMap::new();
        for v in n.values().filter(|v| jx::str_(v, "kind") == Some("module")) {
            let name = jx::str_(v, "name").unwrap_or("").to_string();
            let mut set: BTreeSet<String> = jx::strs(v, "deployment_units").into_iter().map(str::to_string).collect();
            if set.is_empty() {
                set.insert(name.clone());
            }
            units.insert(name, set);
        }
        let mut size = BTreeMap::new();
        for us in units.values() {
            for u in us {
                *size.entry(u.clone()).or_insert(0) += 1;
            }
        }

        SkeletonIndex {
            project,
            n,
            edges,
            table_nodes,
            db_state,
            raw_context: jx::get(sk, "context").cloned().unwrap_or(Json::Null),
            context,
            handlers,
            cs_nodes_by_method,
            type_nodes,
            methods_by_owner,
            entities,
            calls,
            over,
            wiring,
            module,
            units,
            size,
        }
    }

    /// Узел по ID.
    pub fn node(&self, id: &str) -> Option<&Node> {
        self.n.get(id)
    }

    /// Развёртывание единицы: из `deployment_units` модуля метода выбирается с наименьшим размером, затем по имени.
    pub fn unit_of(&self, m: &str) -> String {
        let modname = self.module.get(m).cloned().flatten().unwrap_or_default();
        let units = self.units.get(&modname).cloned().unwrap_or_else(|| BTreeSet::from([modname.clone()]));
        units.into_iter().min_by_key(|u| (self.size.get(u).copied().unwrap_or(0), u.clone())).unwrap_or_default()
    }

    /// Все переопределяющие методы транзитивно.
    pub fn cha(&self, m: &str) -> BTreeSet<String> {
        let mut out = BTreeSet::new();
        let mut st = vec![m.to_string()];
        while let Some(x) = st.pop() {
            if let Some(os) = self.over.get(&x) {
                for o in os {
                    if out.insert(o.clone()) {
                        st.push(o.clone());
                    }
                }
            }
        }
        out
    }

    pub fn get_table_records(&self, table_or_node: &str) -> &[crate::db::Row] {
        self.db_state.get_table(table_or_node)
    }
}

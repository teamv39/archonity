//! Индекс скелета (`engine/adapters/skeleton.py::SkeletonIndex`). Порядок вставки значим: `IndexMap`.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use anyhow::Result;
use indexmap::IndexMap;
use serde_json::Value as Json;

use crate::db::DatabaseState;
use crate::entities::EntityFacts;

/// Узел скелета как есть (`kind`, `owner`, `module`, `annotations`, …).
pub type Node = Json;

pub struct SkeletonIndex {
    pub project: String,
    /// Узлы по ID, в порядке файла.
    pub n: IndexMap<String, Node>,
    pub table_nodes: IndexMap<String, Node>,
    pub db_state: DatabaseState,
    /// Поле `context` скелета, разобранное `parse_context`: `user_name`, даты, баланс.
    pub context: IndexMap<String, Json>,
    /// `(ID метода, глагол, сегменты пути)`.
    pub handlers: Vec<(String, Option<String>, Vec<String>)>,
    pub cs_nodes_by_method: IndexMap<String, Vec<Node>>,
    pub type_nodes: IndexMap<String, Node>,
    pub methods_by_owner: IndexMap<String, Vec<(String, Node)>>,
    pub entities: EntityFacts,
    /// Рёбра `calls` скелета: метод -> цели (call_site приведён к методу).
    pub calls: BTreeMap<String, BTreeSet<String>>,
    /// Рёбра `overrides`: переопределённый метод -> переопределяющие.
    pub over: BTreeMap<String, BTreeSet<String>>,
    /// `remote_call`, `message_delivery`, `runtime_dispatch`, `data_access`: метод -> цели.
    pub wiring: BTreeMap<String, BTreeMap<String, BTreeSet<String>>>,
    /// Метод -> модуль.
    pub module: IndexMap<String, Option<String>>,
    pub units: BTreeMap<String, BTreeSet<String>>,
    pub size: BTreeMap<String, usize>,
}

impl SkeletonIndex {
    /// `skeleton_path` — `.json.gz`; дамп БД ищется рядом (`default_db_dump`), если `db_dump` не задан.
    pub fn load(_skeleton_path: &Path, _db_dump: Option<&Path>, _entity_ir: Option<&Path>) -> Result<SkeletonIndex> {
        todo!("P1")
    }

    pub fn unit_of(&self, _m: &str) -> String {
        todo!("P1")
    }

    /// Все переопределяющие методы транзитивно.
    pub fn cha(&self, _m: &str) -> BTreeSet<String> {
        todo!("P1")
    }
}

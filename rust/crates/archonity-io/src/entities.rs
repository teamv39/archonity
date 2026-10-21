//! Факты archparse о сущностях (`engine/entities.py`, `data/entity_ir.json`), привязанные к скелету.

use std::collections::BTreeSet;
use std::path::Path;

use anyhow::Result;
use indexmap::IndexMap;

use crate::skeleton::Node;

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
}

#[derive(Clone, Debug, Default)]
pub struct EntityFacts {
    pub entities: IndexMap<String, Entity>,
    pub calls_by_method: IndexMap<String, Vec<RepositoryCall>>,
    /// Конструкторы с вызовом проектного метода в теле.
    pub ctors_with_project_calls: BTreeSet<String>,
}

impl EntityFacts {
    /// Нет файла — пустые факты (правило загрузки сущностей выключено), как в Python.
    pub fn load(_path: Option<&Path>) -> Result<EntityFacts> {
        todo!("P1")
    }

    /// Привязка к скелету: call_site по `(file, line, col)`, таблицы `data_access`, ID конструкторов.
    pub fn bind(&mut self, _nodes: &IndexMap<String, Node>, _edges: &[serde_json::Value]) {
        todo!("P1")
    }

    /// `(загружена, причина)`; `None` — решения нет.
    pub fn collection_table_loaded(&self, _method: &str, _table: &str) -> Option<(bool, String)> {
        todo!("P1")
    }

    /// Разрешённые конструкторы по режиму (`caller_only`, `all`, `off`); `None` — без ограничения.
    pub fn allowed_ctors(&self, _mode: &str) -> Option<BTreeSet<String>> {
        todo!("P1")
    }
}

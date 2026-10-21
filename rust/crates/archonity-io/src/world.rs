//! Типы и мир БД исполнителя (`engine/executor/world.py`). Значения — из `archonity-model`.

use std::path::Path;

use archonity_model::values::Value;
use indexmap::IndexMap;
use serde_json::Value as Json;

use crate::db::{DatabaseState, Row};
use crate::skeleton::Node;

pub fn snake(_name: &str) -> String {
    todo!("P1")
}

pub fn camel(_col: &str) -> String {
    todo!("P1")
}

/// Свежий UUID мира: детерминированный счётчик (Python: `fresh_uuid`).
pub fn fresh_uuid() -> String {
    todo!("P1")
}

/// Литералы Java из текста аргументов (`parse_java_args`).
pub fn parse_java_args(_text: &str) -> Vec<Json> {
    todo!("P1")
}

pub fn column_of(_field: &Node) -> String {
    todo!("P1")
}

/// Свойство и условия производного запроса: `findByStatusAndId` -> `("find", [...])`.
pub fn derived_props(_name: &str) -> Option<(String, Vec<String>)> {
    todo!("P1")
}

/// Условия native query: `(колонка, номер параметра)`.
pub fn native_query_conds(_sql: &str) -> Option<Vec<(String, usize)>> {
    todo!("P1")
}

pub fn optional_of(_objs: Vec<Value>, _exact: bool, _fqn: &str) -> Value {
    todo!("P1")
}

/// Индекс типов проекта: разрешение имён, поля, методы, константы enum.
pub struct TypeIndex {}

impl TypeIndex {
    pub fn new(_nodes: &IndexMap<String, Node>, _edges: &[Json], _targets_root: Option<&Path>) -> TypeIndex {
        todo!("P1")
    }

    pub fn resolve(&self, _fqn: Option<&str>, _module: Option<&str>) -> Option<String> {
        todo!("P1")
    }

    pub fn resolve_simple(&self, _simple: &str, _module: Option<&str>) -> Option<String> {
        todo!("P1")
    }

    pub fn all_fields(&self, _type_id: Option<&str>) -> Vec<Node> {
        todo!("P1")
    }

    pub fn is_enum(&self, _type_id: Option<&str>) -> bool {
        todo!("P1")
    }

    pub fn fqn(&self, _type_id: Option<&str>) -> Option<String> {
        todo!("P1")
    }

    pub fn method_of(&self, _type_id: Option<&str>, _name: &str, _arity: Option<usize>) -> Option<String> {
        todo!("P1")
    }

    /// Константы enum: имя и литералы конструктора.
    pub fn enum_constants(&self, _type_id: &str) -> Vec<(String, Vec<Json>)> {
        todo!("P1")
    }
}

/// Мир БД сценария: строки <-> объекты, запросы, сохранение.
pub struct World {
    pub db: DatabaseState,
    /// Сохранённые за сценарий строки: `(таблица, строка)`.
    pub saved: Vec<(String, Row)>,
}

impl World {
    pub fn rows(&self, _table: &str) -> &[Row] {
        todo!("P1")
    }

    pub fn columns(&self, _table: &str) -> Vec<String> {
        todo!("P1")
    }

    pub fn row_to_obj(&mut self, _fqn: &str, _row: &Row, _module: Option<&str>) -> Value {
        todo!("P1")
    }

    pub fn obj_to_row(&mut self, _fqn: &str, _obj: &Value, _module: Option<&str>) -> Row {
        todo!("P1")
    }

    /// Выборка по условиям `(свойство, значение)`; второй результат — точность.
    pub fn select(&mut self, _fqn: &str, _conds: &[(String, Value)], _module: Option<&str>) -> (Vec<Value>, bool) {
        todo!("P1")
    }

    pub fn save(&mut self, _fqn: &str, _obj: &Value, _module: Option<&str>) -> bool {
        todo!("P1")
    }

    pub fn delete(&mut self, _fqn: &str, _conds: &[(String, Value)], _module: Option<&str>) -> usize {
        todo!("P1")
    }
}

//! Состояние БД (`engine/adapters/db.py`): таблицы дампа `db-after-warmup.sql.gz`, `fork` на сценарий.

use std::path::Path;

use anyhow::Result;
use indexmap::IndexMap;
use serde_json::Value as Json;

/// Строка таблицы: колонка -> ячейка (`null`, число, строка).
pub type Row = IndexMap<String, Json>;

#[derive(Clone, Debug, Default)]
pub struct DatabaseState {
    pub tables: IndexMap<String, Vec<Row>>,
    pub table_aliases: IndexMap<String, String>,
    pub table_columns: IndexMap<String, Vec<String>>,
}

impl DatabaseState {
    pub fn normalize_table_name(&self, _table_name: &str) -> String {
        todo!("P1")
    }

    pub fn get_table(&self, _table_name: &str) -> &[Row] {
        todo!("P1")
    }

    pub fn get_columns(&self, _table_name: &str) -> Vec<String> {
        todo!("P1")
    }

    pub fn table_names(&self) -> Vec<String> {
        todo!("P1")
    }

    pub fn insert(&mut self, _table_name: &str, _row: Row) {
        todo!("P1")
    }

    pub fn update(&mut self, _table_name: &str, _updates: &Row, _filters: &Row) -> usize {
        todo!("P1")
    }

    /// Независимая копия: мир сценария и откат шага.
    pub fn fork(&self) -> DatabaseState {
        todo!("P1")
    }
}

pub fn load_db_dump(_gz_path: &Path) -> Result<DatabaseState> {
    todo!("P1")
}

/// Поле `context` скелета: пассажир, даты, баланс (`parse_context`).
pub fn parse_context(_text: &str) -> IndexMap<String, Json> {
    todo!("P1")
}

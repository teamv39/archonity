//! Обёртка ответа проекта (`engine/executor/envelope.py`): класс, поле статуса, значение успеха.

use std::path::Path;

use archonity_io::SkeletonIndex;
use serde_json::Value as Json;

use crate::ir::IrStore;

#[derive(Clone, Debug)]
pub struct Envelope {
    /// Простое имя класса обёртки.
    pub name: String,
    /// Поле статуса (первый аргумент конструктора).
    pub status: String,
    /// Значение статуса при успехе.
    pub success: Json,
    pub data: Option<String>,
}

impl Envelope {
    pub fn is_type(&self, _type_name: Option<&str>) -> bool {
        todo!("D2")
    }

    pub fn setter(&self) -> String {
        todo!("D2")
    }

    pub fn getter(&self) -> String {
        todo!("D2")
    }
}

/// Обёртка проекта по скелету, IR и коду UI; `None`, если вывести не из чего.
pub fn derive(_ix: &SkeletonIndex, _ir: &IrStore, _targets_root: Option<&Path>) -> Option<Envelope> {
    todo!("D2")
}

/// Каталог UI пакета задачи (`find_ui_dir`, `ui_files` из `engine/grounding/ui_catalog.py`).
pub fn find_ui_dir(_targets_root: &Path) -> Option<std::path::PathBuf> {
    todo!("D2")
}

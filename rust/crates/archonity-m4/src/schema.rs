//! Виды сущностей, их ID-поля и простые имена типов для разрешения ссылок шагов (`engine/executor/schema.py`).

use archonity_io::SkeletonIndex;
use indexmap::IndexMap;

use crate::manifest::EntityKind;

pub struct EntitySchema {
    pub manifest: IndexMap<String, EntityKind>,
    pub user_fields: Vec<String>,
}

impl EntitySchema {
    pub fn new(_index: Option<&SkeletonIndex>) -> EntitySchema {
        todo!("D1")
    }

    pub fn known_kinds(&self) -> Vec<String> {
        todo!("D1")
    }

    pub fn id_fields(&self, _kind: &str) -> Vec<String> {
        todo!("D1")
    }

    pub fn primary_id_field(&self, _kind: &str) -> Option<String> {
        todo!("D1")
    }

    pub fn kind_hints(&self, _kind: &str) -> Vec<String> {
        todo!("D1")
    }

    /// 3 — совпадает, 2 — префикс, 1 — содержит, 0 — нет.
    pub fn kind_rank(&self, _fqn: Option<&str>, _kind: &str) -> u8 {
        todo!("D1")
    }

    pub fn is_kind(&self, fqn: Option<&str>, kind: &str) -> bool {
        self.kind_rank(fqn, kind) > 0
    }
}

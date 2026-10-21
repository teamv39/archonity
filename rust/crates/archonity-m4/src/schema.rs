//! Виды сущностей, их ID-поля и простые имена типов для разрешения ссылок шагов (`engine/executor/schema.py`).

use archonity_io::SkeletonIndex;
use archonity_model::names::simple_name;
use indexmap::IndexMap;

use crate::manifest::{entity_kinds, EntityKind};

const USER_FIELDS: [&str; 3] = ["accountId", "userId", "loginId"];

pub struct EntitySchema {
    pub manifest: IndexMap<String, EntityKind>,
    kind_hints: IndexMap<String, Vec<String>>,
    id_fields: IndexMap<String, Vec<String>>,
    pub user_fields: Vec<String>,
}

impl EntitySchema {
    pub fn new(index: Option<&SkeletonIndex>) -> EntitySchema {
        let manifest = index.map(entity_kinds).unwrap_or_default();
        let mut kind_hints = IndexMap::new();
        let mut id_fields = IndexMap::new();
        for (k, ek) in &manifest {
            let mut hints: Vec<String> = Vec::new();
            for t in &ek.types {
                let h = simple_name(Some(t), true);
                if !hints.contains(&h) {
                    hints.push(h);
                }
            }
            kind_hints.insert(k.clone(), hints);
            id_fields.insert(k.clone(), ek.id_fields.clone());
        }
        EntitySchema { manifest, kind_hints, id_fields, user_fields: USER_FIELDS.iter().map(|s| s.to_string()).collect() }
    }

    pub fn known_kinds(&self) -> Vec<&String> {
        self.id_fields.keys().collect()
    }

    pub fn is_known(&self, kind: &str) -> bool {
        self.id_fields.contains_key(kind)
    }

    /// ID-поля вида: из манифеста; для вида вне манифеста — `<вид>Id`, `<вид>sId` (или без s), `id`.
    pub fn id_fields(&self, kind: &str) -> Vec<String> {
        if let Some(f) = self.id_fields.get(kind) {
            return f.clone();
        }
        let mut cs = kind.chars();
        let k = cs.next().map(|f| f.to_lowercase().collect::<String>() + cs.as_str()).unwrap_or_default();
        if let Some(stem) = k.strip_suffix('s') {
            vec![format!("{k}Id"), format!("{stem}Id"), "id".to_string()]
        } else {
            vec![format!("{k}Id"), format!("{k}sId"), "id".to_string()]
        }
    }

    /// Главное ID-поле вида: первое из ID-полей.
    pub fn primary_id_field(&self, kind: &str) -> Option<String> {
        self.id_fields(kind).into_iter().next()
    }

    pub fn kind_hints(&self, kind: &str) -> Vec<String> {
        self.kind_hints.get(kind).cloned().unwrap_or_else(|| vec![kind.to_lowercase()])
    }

    /// Насколько тип похож на вид сущности: 3 — совпадает, 2 — префикс, 1 — содержит, 0 — нет.
    pub fn kind_rank(&self, fqn: Option<&str>, kind: &str) -> u8 {
        let s = simple_name(fqn, true);
        let mut best = 0;
        for h in self.kind_hints(kind) {
            if s == h || s == format!("{h}s") {
                best = best.max(3);
            } else if s.starts_with(&h) {
                best = best.max(2);
            } else if s.contains(&h) {
                best = best.max(1);
            }
        }
        best
    }

    pub fn is_kind(&self, fqn: Option<&str>, kind: &str) -> bool {
        self.kind_rank(fqn, kind) > 0
    }
}

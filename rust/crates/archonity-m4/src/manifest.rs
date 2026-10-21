//! Манифест сущностей (`engine/manifest.py`): виды, ID-поля, таблицы по аннотациям скелета.

use archonity_io::SkeletonIndex;
use indexmap::IndexMap;

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
pub fn kind_name(_simple: &str) -> String {
    todo!("D1")
}

pub fn entity_kinds(_ix: &SkeletonIndex) -> IndexMap<String, EntityKind> {
    todo!("D1")
}

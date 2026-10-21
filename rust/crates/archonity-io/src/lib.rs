//! Загрузка входов, мир БД и выходы (ADR-008, rust_port_split.md). Владелец — Паша.
//!
//! Этап 0 даёт только сигнатуры с `todo!()`: что `archonity-m4` берёт отсюда (раздел «Контракт» rust_port_split.md).
//! Python-источники: `engine/adapters/{skeleton,db,submission}.py`, `engine/{entities,decisions,evidence}.py`,
//! `engine/executor/world.py`. Срезы для сверки загрузчиков — `scripts/rust_oracles.py slices`.

pub mod db;
pub mod decisions;
pub mod entities;
pub mod evidence;
pub mod json_py;
pub mod jx;
pub mod skeleton;
pub mod submission;
pub mod world;

pub use db::DatabaseState;
pub use decisions::DecisionLedger;
pub use entities::EntityFacts;
pub use skeleton::SkeletonIndex;
pub use world::{TypeIndex, World};

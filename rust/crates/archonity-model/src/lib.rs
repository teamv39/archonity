//! Контракт между crate (ADR-008, rust_port_split.md): значения M4, `StepRequest`, рёбра шага, флаги правил.
//! Владелец — Денис. Правка публичной сигнатуры после этапа 0 — отдельный маленький PR, второй человек знает о нём до мержа.

pub mod edges;
pub mod flags;
pub mod names;
pub mod pyfmt;
pub mod request;
pub mod values;

pub use edges::StepEdges;
pub use flags::RuleFlags;
pub use request::{canon_value, group_sent, BodyGroup, ScenarioContext, StepRequest};
pub use values::Value;

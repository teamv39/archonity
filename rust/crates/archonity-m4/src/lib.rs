//! Исполнитель M4 (ADR-005, ADR-008). Владелец — Денис.
//!
//! Публичный вход один: [`step::StepExecutor`]. Python-источники: `engine/executor/*.py` (без `judge.py`), `engine/manifest.py`.
//! Тела методов (IR) — `data/ir/*.json`, читаются как `serde_json::Value` с сохранением порядка ключей.

pub mod envelope;
pub mod interpreter;
pub mod ir;
pub mod library;
pub mod manifest;
pub mod schema;
pub mod step;

pub use step::StepExecutor;

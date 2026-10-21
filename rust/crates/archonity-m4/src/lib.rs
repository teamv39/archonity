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

use std::io::Write;
use std::sync::{Mutex, OnceLock};

static TRACE: OnceLock<Option<Mutex<std::fs::File>>> = OnceLock::new();

/// Трасса вызовов при `ARCHONITY_TRACE=<файл>` (как в Python): строка `глубина<TAB>ID метода`.
pub fn trace(line: &str) {
    let t = TRACE.get_or_init(|| {
        std::env::var("ARCHONITY_TRACE")
            .ok()
            .and_then(|p| std::fs::OpenOptions::new().create(true).append(true).open(p).ok())
            .map(Mutex::new)
    });
    if let Some(f) = t {
        let mut f = f.lock().unwrap();
        let _ = writeln!(f, "{line}");
    }
}

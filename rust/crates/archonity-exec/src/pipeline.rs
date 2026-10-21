//! Цикл сценариев (`engine/pipeline.py`, путь M4): контекст пассажира, шаги, R19, запись выдачи.

use anyhow::Result;
use archonity_io::SkeletonIndex;
use archonity_model::ScenarioContext;

use crate::RunConfig;

pub fn run(_cfg: &RunConfig) -> Result<()> {
    todo!("P3")
}

/// Пассажир из контекста задачи («pre-registered user <имя>»); ID — поле `@Id` сущности `UserDetails` в строке дампа.
pub fn resolve_passenger_context(_index: &SkeletonIndex, _scenario_id: &str) -> ScenarioContext {
    todo!("P3")
}

//! Шаг сценария (`engine/executor/step.py`): параметры, DTO, ссылки на прежние шаги, повтор при отказе.

use std::path::Path;
use std::rc::Rc;

use anyhow::Result;
use archonity_io::{DecisionLedger, SkeletonIndex};
use archonity_model::{RuleFlags, ScenarioContext, StepEdges, StepRequest};

pub struct StepExecutor {
    pub index: Rc<SkeletonIndex>,
    pub flags: RuleFlags,
}

impl StepExecutor {
    /// `ir_dir` — `data/ir/`; `targets_root` — исходники проекта (каталог UI), если есть.
    pub fn new(_index: Rc<SkeletonIndex>, _flags: RuleFlags, _ir_dir: &Path, _targets_root: Option<&Path>) -> Result<StepExecutor> {
        todo!("D3")
    }

    /// Мир БД сценария: копия дампа.
    pub fn begin_scenario(&mut self, _sid: &str) {
        todo!("D3")
    }

    /// Исполняет шаг (запрос после R20) и пишет решения шага в журнал. Рёбра — до Spring Security и M5.
    pub fn run_step(&mut self, _req: &StepRequest, _ctx: &ScenarioContext, _ledger: &mut DecisionLedger) -> Result<StepEdges> {
        todo!("D3")
    }
}

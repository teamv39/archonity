//! Журнал решений по рёбрам (`engine/decisions.py`, evidence.json v2). Порядок записей значим.

use indexmap::IndexMap;
use serde_json::Value as Json;

pub const INCLUDE: &str = "include";
pub const PRUNE: &str = "prune";
pub const DISCARD: &str = "discard";

pub fn edge_key(relation: &str, source: &str, target: &str) -> String {
    format!("{relation}|{source}|{target}")
}

#[derive(Clone, Debug)]
pub struct Decision {
    pub step: Option<i64>,
    pub op: String,
    pub source_type: String,
    pub rule: String,
    /// Детали записи (`via`, …) в порядке вставки.
    pub detail: IndexMap<String, Json>,
}

#[derive(Debug, Default)]
pub struct DecisionLedger {
    pub scenarios: IndexMap<String, IndexMap<String, Vec<Decision>>>,
    #[allow(dead_code)] // читают тела P2
    sid: Option<String>,
    #[allow(dead_code)]
    step: Option<i64>,
}

impl DecisionLedger {
    pub fn begin_scenario(&mut self, _scenario_id: &str) {
        todo!("P2")
    }

    pub fn begin_step(&mut self, _step: Option<i64>) {
        todo!("P2")
    }

    /// Ошибка, если `begin_scenario` не вызван.
    pub fn scenario_id(&self) -> &str {
        todo!("P2")
    }

    pub fn include(&mut self, _relation: &str, _source: &str, _target: &str, _source_type: &str, _rule: &str, _detail: IndexMap<String, Json>) {
        todo!("P2")
    }

    pub fn prune(&mut self, _relation: &str, _source: &str, _target: &str, _source_type: &str, _rule: &str, _detail: IndexMap<String, Json>) {
        todo!("P2")
    }

    pub fn discard(&mut self, _relation: &str, _source: &str, _target: &str, _source_type: &str, _rule: &str, _detail: IndexMap<String, Json>) {
        todo!("P2")
    }

    /// Метод исполнен: ребро `executes` от `scenario:<id>`.
    pub fn execute(&mut self, _method: &str, _source_type: &str, _rule: &str, _detail: IndexMap<String, Json>) {
        todo!("P2")
    }

    pub fn final_edges(&self, _scenario_id: &str) -> Vec<(String, String, String)> {
        todo!("P2")
    }

    /// Тело `decisions.json` (version 2).
    pub fn to_json(&self) -> Json {
        todo!("P2")
    }
}

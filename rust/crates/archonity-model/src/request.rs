//! `StepRequest` (выход M1, `engine/grounding/request.py`) и контекст пассажира (`engine/pipeline.py`).

use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::Value as Json;

/// Шаг сценария, сопоставленный с обработчиком. Читается из `step_requests_raw.json` (шаг до R20).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StepRequest {
    pub scenario: String,
    pub step: i64,
    pub action: String,
    pub handler: String,
    pub http: IndexMap<String, String>,
    #[serde(default)]
    pub params: IndexMap<String, Json>,
    #[serde(default = "success")]
    pub expected_outcome: String,
    #[serde(default)]
    pub refs: IndexMap<String, String>,
    #[serde(default)]
    pub ui_source: Option<Json>,
    #[serde(default)]
    pub body_src: IndexMap<String, String>,
    #[serde(default)]
    pub grounding: IndexMap<String, Json>,
}

fn success() -> String {
    "success".to_string()
}

/// Пассажир сценария для M4 до шага входа (`ScenarioContext`).
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ScenarioContext {
    pub user_name: Option<String>,
    pub account_id: Option<String>,
    pub scenario_id: String,
}

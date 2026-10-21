//! `submission.json` в формате организаторов (`engine/adapters/submission.py`).

use std::path::Path;

use anyhow::Result;
use indexmap::IndexMap;

/// Ребро ответа: `(source, relation, target)`.
pub type Edge = (String, String, String);

pub struct SubmissionAdapter {
    pub project: String,
    pub scenarios: IndexMap<String, Vec<Edge>>,
}

impl SubmissionAdapter {
    pub fn new(project: &str) -> SubmissionAdapter {
        SubmissionAdapter { project: project.to_string(), scenarios: IndexMap::new() }
    }

    pub fn add_scenario_edges(
        &mut self,
        _scenario_id: &str,
        _methods: &[String],
        _calls: &[(String, String)],
        _remote: &[(String, String)],
        _data: &[(String, String)],
    ) {
        todo!("P2")
    }

    /// Байт в байт с Python (`json_py`).
    pub fn save(&self, _path: &Path) -> Result<()> {
        todo!("P2")
    }
}

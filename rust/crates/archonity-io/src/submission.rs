//! `submission.json` в формате организаторов (`engine/adapters/submission.py`).

use std::collections::BTreeSet;
use std::path::Path;

use anyhow::Result;
use indexmap::IndexMap;
use serde_json::{json, Value as Json};

use crate::evidence::EvidenceLogger;
use crate::json_py::dumps_indent1;

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

    /// Рёбра сценария: `executes`, `calls`, `remote`, `data`, каждый вид по возрастанию. Доказательства рёбер `remote`,
    /// `data` и маршрутов шлюза — в `evidence`, если он есть.
    pub fn add_scenario_edges(
        &mut self,
        scenario_id: &str,
        methods: &BTreeSet<String>,
        calls: &BTreeSet<(String, String)>,
        remote: &BTreeSet<(String, String)>,
        data: &BTreeSet<(String, String)>,
        evidence: Option<&mut EvidenceLogger>,
    ) {
        let mut edges: Vec<Edge> = Vec::new();
        for m in methods {
            edges.push((format!("scenario:{scenario_id}"), "executes".into(), m.clone()));
        }
        for (rel, set) in [("calls", calls), ("remote", remote), ("data", data)] {
            for (s, t) in set {
                edges.push((s.clone(), rel.into(), t.clone()));
            }
        }
        self.scenarios.insert(scenario_id.to_string(), edges);
        if let Some(ev) = evidence {
            for (s, t) in remote {
                ev.record_remote_call(s, t);
            }
            for (s, t) in data {
                ev.record_data_access(s, t);
            }
            for m in methods {
                if m.starts_with("method:") {
                    if let Some(svc) = m.split(':').nth(1) {
                        ev.record_gateway_route(svc);
                    }
                }
            }
        }
    }

    pub fn to_json(&self) -> Json {
        let mut ids: Vec<&String> = self.scenarios.keys().collect();
        ids.sort();
        let scenarios: serde_json::Map<String, Json> = ids
            .into_iter()
            .map(|sid| {
                let edges: Vec<Json> = self.scenarios[sid]
                    .iter()
                    .map(|(s, r, t)| json!({"source": s, "relation": r, "target": t}))
                    .collect();
                (sid.clone(), json!({"edges": edges}))
            })
            .collect();
        json!({"project": self.project, "scenarios": scenarios})
    }

    /// Байт в байт с Python (`json.dump(..., ensure_ascii=False, indent=1)`, без перевода строки в конце).
    pub fn save(&self, path: &Path) -> Result<()> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        std::fs::write(path, dumps_indent1(&self.to_json()))?;
        Ok(())
    }
}

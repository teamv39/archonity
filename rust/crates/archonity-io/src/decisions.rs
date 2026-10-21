//! Журнал решений по рёбрам (`engine/decisions.py`, evidence.json v2).
//!
//! Единственный источник ответа на вопрос «почему это ребро есть или его нет»: записи делают сами M4, правило Spring
//! Security и проекция M5 в момент решения. Ключ ребра — `relation|source|target`.

use anyhow::{bail, Result};
use indexmap::IndexMap;
use serde_json::{json, Value as Json};

pub const INCLUDE: &str = "include";
pub const PRUNE: &str = "prune";
pub const DISCARD: &str = "discard";

const SOURCE_TYPES: [&str; 6] = ["SKELETON", "IR_BRANCH", "IR_CALL", "STATE", "DEFAULT_RULE", "FRAMEWORK_RULE"];

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

impl Decision {
    pub fn to_json(&self) -> Json {
        let mut m = serde_json::Map::new();
        m.insert("step".into(), self.step.map(Json::from).unwrap_or(Json::Null));
        m.insert("op".into(), json!(self.op));
        m.insert("source_type".into(), json!(self.source_type));
        m.insert("rule".into(), json!(self.rule));
        for (k, v) in &self.detail {
            m.insert(k.clone(), v.clone());
        }
        Json::Object(m)
    }
}

#[derive(Debug, Default)]
pub struct DecisionLedger {
    scenarios: IndexMap<String, IndexMap<String, Vec<Decision>>>,
    sid: Option<String>,
    step: Option<i64>,
}

pub fn detail(pairs: &[(&str, Json)]) -> IndexMap<String, Json> {
    pairs.iter().map(|(k, v)| (k.to_string(), v.clone())).collect()
}

impl DecisionLedger {
    pub fn begin_scenario(&mut self, scenario_id: &str) {
        self.sid = Some(scenario_id.to_string());
        self.step = None;
        self.scenarios.insert(scenario_id.to_string(), IndexMap::new());
    }

    pub fn begin_step(&mut self, step: Option<i64>) {
        self.step = step;
    }

    /// Ошибка, если `begin_scenario` не вызван.
    pub fn scenario_id(&self) -> Result<&str> {
        match &self.sid {
            Some(s) => Ok(s),
            None => bail!("DecisionLedger: begin_scenario не вызван"),
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn record(&mut self, op: &str, relation: &str, source: &str, target: &str, source_type: &str, rule: &str, detail: IndexMap<String, Json>) -> Result<()> {
        if !SOURCE_TYPES.contains(&source_type) {
            bail!("Неизвестный source_type: {source_type}");
        }
        let key = edge_key(relation, source, target);
        let sid = self.scenario_id()?.to_string();
        let step = self.step;
        self.scenarios.entry(sid).or_default().entry(key).or_default().push(Decision {
            step,
            op: op.to_string(),
            source_type: source_type.to_string(),
            rule: rule.to_string(),
            detail,
        });
        Ok(())
    }

    pub fn include(&mut self, relation: &str, source: &str, target: &str, source_type: &str, rule: &str, detail: IndexMap<String, Json>) -> Result<()> {
        self.record(INCLUDE, relation, source, target, source_type, rule, detail)
    }

    pub fn prune(&mut self, relation: &str, source: &str, target: &str, source_type: &str, rule: &str, detail: IndexMap<String, Json>) -> Result<()> {
        self.record(PRUNE, relation, source, target, source_type, rule, detail)
    }

    pub fn discard(&mut self, relation: &str, source: &str, target: &str, source_type: &str, rule: &str, detail: IndexMap<String, Json>) -> Result<()> {
        self.record(DISCARD, relation, source, target, source_type, rule, detail)
    }

    /// Метод исполнен: ребро `executes` от `scenario:<id>`.
    pub fn execute(&mut self, method: &str, source_type: &str, rule: &str, detail: IndexMap<String, Json>) -> Result<()> {
        let src = format!("scenario:{}", self.scenario_id()?);
        self.include("executes", &src, method, source_type, rule, detail)
    }

    /// Шаги, после которых ребро осталось включённым (`prune` не снимает включение, `discard` снимает).
    fn included_steps(decisions: &[Decision]) -> Vec<Option<i64>> {
        let mut state: IndexMap<Option<i64>, bool> = IndexMap::new();
        for d in decisions {
            if d.op == INCLUDE {
                state.insert(d.step, true);
            } else if d.op == DISCARD {
                state.insert(d.step, false);
            }
        }
        state.into_iter().filter(|(_, on)| *on).map(|(s, _)| s).collect()
    }

    /// Рёбра ответа сценария `(relation, source, target)` по журналу.
    pub fn final_edges(&self, scenario_id: &str) -> Vec<(String, String, String)> {
        let mut out = Vec::new();
        if let Some(sc) = self.scenarios.get(scenario_id) {
            for (key, decisions) in sc {
                if !Self::included_steps(decisions).is_empty() {
                    let mut it = key.splitn(3, '|');
                    out.push((it.next().unwrap_or("").into(), it.next().unwrap_or("").into(), it.next().unwrap_or("").into()));
                }
            }
        }
        out
    }

    fn scenario_json(&self, sid: &str) -> Json {
        let mut result = serde_json::Map::new();
        if let Some(sc) = self.scenarios.get(sid) {
            let mut keys: Vec<&String> = sc.keys().collect();
            keys.sort();
            for key in keys {
                let decisions = &sc[key];
                let mut steps = Self::included_steps(decisions);
                let main: &Decision = if !steps.is_empty() {
                    decisions.iter().find(|d| d.op == INCLUDE && steps.contains(&d.step)).unwrap()
                } else {
                    decisions.iter().rev().find(|d| d.op != INCLUDE).unwrap_or_else(|| decisions.last().unwrap())
                };
                steps.sort_by_key(|s| (s.is_none(), s.unwrap_or(0)));
                let mut entry = serde_json::Map::new();
                entry.insert("included".into(), Json::Bool(!steps.is_empty()));
                entry.insert("steps".into(), Json::Array(steps.iter().map(|s| s.map(Json::from).unwrap_or(Json::Null)).collect()));
                entry.insert("source_type".into(), json!(main.source_type));
                entry.insert("rule".into(), json!(main.rule));
                for (k, v) in &main.detail {
                    entry.insert(k.clone(), v.clone());
                }
                entry.insert("decisions".into(), Json::Array(decisions.iter().map(Decision::to_json).collect()));
                result.insert(key.clone(), Json::Object(entry));
            }
        }
        Json::Object(result)
    }

    /// Записи шага по ключам рёбер (ключи отсортированы, пустые опущены): формат `journal` в `raw_steps.json`.
    pub fn step_journal(&self, sid: &str, step: i64) -> Json {
        let mut out = serde_json::Map::new();
        if let Some(sc) = self.scenarios.get(sid) {
            let mut keys: Vec<&String> = sc.keys().collect();
            keys.sort();
            for k in keys {
                let ds: Vec<Json> = sc[k].iter().filter(|d| d.step == Some(step)).map(Decision::to_json).collect();
                if !ds.is_empty() {
                    out.insert(k.clone(), Json::Array(ds));
                }
            }
        }
        Json::Object(out)
    }

    /// Тело `decisions.json` (version 2).
    pub fn to_json(&self) -> Json {
        let mut sids: Vec<&String> = self.scenarios.keys().collect();
        sids.sort();
        let scenarios: serde_json::Map<String, Json> = sids.into_iter().map(|s| (s.clone(), self.scenario_json(s))).collect();
        json!({"version": 2, "scenarios": scenarios})
    }
}

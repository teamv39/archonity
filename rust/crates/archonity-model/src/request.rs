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
    /// Группы полей тела, которые UI шлёт только под общим условием (каталог UI, `UIRequest.body_groups`).
    #[serde(default)]
    pub body_groups: Vec<BodyGroup>,
    #[serde(default)]
    pub grounding: IndexMap<String, Json>,
}

/// Группа полей под общим условием UI; `on` — литералы, которые UI ставит, только когда условие верно.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct BodyGroup {
    #[serde(default)]
    pub fields: Vec<String>,
    #[serde(default)]
    pub on: Vec<(String, String)>,
}

/// Значение в одном виде для сравнения (`canon_value`, `engine/grounding/request.py`): `2`, `2.0`, `"2"` — `"2"`.
/// Умолчание Java (0, false, пустая строка, null) — `None`: о том, слал ли UI поле, оно ничего не говорит.
pub fn canon_value(v: &Json) -> Option<String> {
    match v {
        Json::Bool(true) => Some("true".into()),
        Json::Number(n) => canon_f64(n.as_f64()?),
        Json::String(s) if !s.is_empty() => {
            let t = s.trim();
            if t == "true" || t == "false" {
                return canon_value(&Json::Bool(t == "true"));
            }
            let (int, frac) = t.strip_prefix('-').unwrap_or(t).split_once('.').unwrap_or((t.strip_prefix('-').unwrap_or(t), ""));
            let digits = |x: &str| !x.is_empty() && x.bytes().all(|b| b.is_ascii_digit());
            if digits(int) && (frac.is_empty() && !t.ends_with('.') || digits(frac)) {
                return canon_f64(t.parse().ok()?);
            }
            Some(s.clone())
        }
        _ => None,
    }
}

fn canon_f64(f: f64) -> Option<String> {
    if f == 0.0 {
        None
    } else if f.fract() == 0.0 {
        Some(format!("{}", f as i64))
    } else {
        Some(crate::pyfmt::float_repr(f))
    }
}

/// Слал ли UI группу (`group_sent`): в параметрах шага есть поле группы со значением не по умолчанию или литерал,
/// который UI ставит только под условием группы.
pub fn group_sent(group: &BodyGroup, params: &IndexMap<String, Json>) -> bool {
    params.iter().any(|(name, v)| {
        canon_value(v).is_some_and(|c| group.fields.contains(name) || group.on.iter().any(|(f, x)| f == name && *x == c))
    })
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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// Те же случаи, что `tests/test_ui_optional_groups.py::test_canon_value` (паритет с Python).
    #[test]
    fn canon_value_matches_python() {
        let cases = [
            (json!(null), None),
            (json!(false), None),
            (json!(0), None),
            (json!(0.0), None),
            (json!(""), None),
            (json!("0"), None),
            (json!(true), Some("true")),
            (json!(2), Some("2")),
            (json!(2.0), Some("2")),
            (json!("2"), Some("2")),
            (json!(0.5), Some("0.5")),
            (json!("0.5"), Some("0.5")),
            (json!("false"), None),
            (json!("Suzhou"), Some("Suzhou")),
            (json!([1]), None),
        ];
        for (v, want) in cases {
            assert_eq!(canon_value(&v).as_deref(), want, "{v}");
        }
    }

    #[test]
    fn group_sent_needs_non_default_value() {
        let g = BodyGroup { fields: vec!["w".into(), "name".into()], on: vec![("kind".into(), "2".into())] };
        let p = |v: Json| v.as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.clone())).collect::<IndexMap<_, _>>();
        assert!(!group_sent(&g, &p(json!({}))));
        assert!(!group_sent(&g, &p(json!({"w": 0.0, "kind": 0}))));
        assert!(group_sent(&g, &p(json!({"w": 3.0}))));
        assert!(group_sent(&g, &p(json!({"kind": 2}))));
        assert!(!group_sent(&g, &p(json!({"kind": 1}))));
    }
}

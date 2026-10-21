//! M5, R7 (`engine/projection.py::project_constructors`): конструктор в ответе, только если из него исполнился
//! вызов проекта (ADR-006). Рёбер `calls` в конструктор нет никогда.

use std::collections::BTreeSet;

use anyhow::Result;
use archonity_io::DecisionLedger;
use archonity_model::flags::Constructors;

const RULE: &str = "R7:ctor_visibility";

fn is_ctor(id: &str) -> bool {
    id.contains("#<init>(")
}

pub fn project_constructors(
    methods: &mut BTreeSet<String>,
    calls: &mut BTreeSet<(String, String)>,
    remote: &mut BTreeSet<(String, String)>,
    data: &mut BTreeSet<(String, String)>,
    mode: Constructors,
    ledger: &mut DecisionLedger,
) -> Result<()> {
    if mode == Constructors::All {
        return Ok(());
    }
    for (rel, edges) in [("calls", &mut *calls), ("remote", &mut *remote), ("data", &mut *data)] {
        let snapshot: Vec<(String, String)> = edges.iter().cloned().collect();
        for (s, t) in snapshot {
            let why = if mode == Constructors::Off && (is_ctor(&s) || is_ctor(&t)) {
                format!("{RULE}:off")
            } else if rel == "calls" && is_ctor(&t) {
                format!("{RULE}:no_calls_into_ctor")
            } else {
                continue;
            };
            edges.remove(&(s.clone(), t.clone()));
            ledger.discard(rel, &s, &t, "FRAMEWORK_RULE", &why, Default::default())?;
        }
    }
    let sources: BTreeSet<&String> = calls.iter().chain(remote.iter()).chain(data.iter()).map(|(s, _)| s).collect();
    let drop: Vec<String> = methods.iter().filter(|m| is_ctor(m) && !sources.contains(m)).cloned().collect();
    for m in drop {
        methods.remove(&m);
        let why = if mode == Constructors::Off { format!("{RULE}:off") } else { format!("{RULE}:no_project_call") };
        let src = format!("scenario:{}", ledger.scenario_id()?);
        ledger.discard("executes", &src, &m, "FRAMEWORK_RULE", &why, Default::default())?;
    }
    Ok(())
}

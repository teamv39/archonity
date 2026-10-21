//! Прогон `StepExecutor` по шагам после R20 из `raw_steps.json` (оракул Python) для сверки рёбер и журнала:
//! `replay-steps <скелет.json.gz> <entity_ir.json> <каталог IR> <исходники проекта> <raw_steps.json> <выход>`.
//! Выход — тот же формат, что у оракула, без поля `request`.

use std::path::Path;
use std::rc::Rc;

use archonity_io::json_py::dumps_indent1;
use archonity_io::{DecisionLedger, SkeletonIndex};
use archonity_m4::StepExecutor;
use archonity_model::{RuleFlags, ScenarioContext, StepRequest};
use serde_json::{json, Value as Json};

fn main() -> anyhow::Result<()> {
    let a: Vec<String> = std::env::args().collect();
    let ix = Rc::new(SkeletonIndex::load(Path::new(&a[1]), None, Path::new(&a[2]))?);
    let mut ex = StepExecutor::new(ix, RuleFlags::default(), Path::new(&a[3]), Some(Path::new(&a[4])))?;
    let raw: Json = serde_json::from_str(&std::fs::read_to_string(&a[5])?)?;
    let only: Vec<String> = a.iter().skip(7).cloned().collect();
    let mut ledger = DecisionLedger::default();
    let mut out = serde_json::Map::new();
    for (sid, sc) in raw.as_object().unwrap() {
        if !only.is_empty() && !only.contains(sid) {
            continue;
        }
        let ctx: ScenarioContext = serde_json::from_value(sc["passenger"].clone())?;
        ledger.begin_scenario(sid);
        ex.begin_scenario(sid);
        let mut steps = Vec::new();
        for st in sc["steps"].as_array().unwrap() {
            let req: StepRequest = serde_json::from_value(st["request"].clone())?;
            ledger.begin_step(Some(req.step));
            let e = match ex.run_step(&req, &ctx, &mut ledger) {
                Ok(e) => e,
                Err(err) => {
                    eprintln!("{sid} шаг {}: {err:#}", req.step);
                    continue;
                }
            };
            let pairs = |s: &std::collections::BTreeSet<(String, String)>| s.iter().map(|(x, y)| json!([x, y])).collect::<Vec<_>>();
            steps.push(json!({
                "step": req.step,
                "methods": e.methods,
                "calls": pairs(&e.calls),
                "remote": pairs(&e.remote),
                "data": pairs(&e.data),
                "journal": ledger.step_journal(sid, req.step),
            }));
        }
        out.insert(sid.clone(), json!({"steps": steps}));
    }
    std::fs::write(&a[6], dumps_indent1(&Json::Object(out)) + "\n")?;
    Ok(())
}

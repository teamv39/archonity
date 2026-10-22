//! Цикл сценариев (`engine/pipeline.py`, путь M4): контекст пассажира, R20, M4, правило Spring Security, M5, R19,
//! запись `submission.json`, `evidence.json`, `decisions.json`.
//!
//! Р2: сбой на шаге не роняет прогон — шаг без рёбер, сбой в сценарии — пустой блок. Сбои пишутся в
//! `exec_failures.json` рядом с выдачей: рамку и `ATTENTION.txt` собирает Python-часть (`run_eval.py`).

use std::collections::BTreeSet;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::rc::Rc;

use anyhow::{anyhow, Context, Result};
use archonity_io::json_py::dumps_indent1;
use archonity_io::evidence::EvidenceLogger;
use archonity_io::submission::SubmissionAdapter;
use archonity_io::{DecisionLedger, SkeletonIndex};
use archonity_m4::StepExecutor;
use archonity_model::flags::UnboundHandlers;
use archonity_model::names::camel_to_snake;
use archonity_model::values::Value;
use archonity_model::{RuleFlags, ScenarioContext, StepEdges, StepRequest};
use indexmap::IndexMap;
use serde_json::{json, Value as Json};

use crate::binding::rebind;
use crate::catalog::HandlerCatalog;
use crate::projection::project_constructors;
use crate::security::apply_spring_security;
use crate::RunConfig;

/// Сбой для ATTENTION (`engine/attention.py::failure`).
fn failure(scenario: Option<&str>, step: Option<i64>, stage: &str, error: &str) -> Json {
    json!({"scenario": scenario, "step": step, "stage": stage, "error": error, "where": ""})
}

fn panic_text(p: Box<dyn std::any::Any + Send>) -> String {
    if let Some(s) = p.downcast_ref::<&str>() {
        format!("panic: {s}")
    } else if let Some(s) = p.downcast_ref::<String>() {
        format!("panic: {s}")
    } else {
        "panic".to_string()
    }
}

pub fn run(cfg: &RunConfig) -> Result<()> {
    let mut flags = RuleFlags::default();
    for r in &cfg.rules {
        let (k, v) = r.split_once('=').ok_or_else(|| anyhow!("--rule ожидает name=value: {r}"))?;
        flags.set(k, v)?;
    }
    let raw: IndexMap<String, Vec<StepRequest>> = serde_json::from_str(
        &std::fs::read_to_string(&cfg.step_requests).with_context(|| format!("не прочитан {}", cfg.step_requests.display()))?,
    )
    .with_context(|| format!("не разобран {}", cfg.step_requests.display()))?;

    let index = Rc::new(SkeletonIndex::load(&cfg.skeleton, cfg.db_dump.as_deref(), &cfg.entity_ir)?);
    let catalog = HandlerCatalog::build(&index);
    let mut evidence = EvidenceLogger::new(&index, cfg.targets.as_deref(), &cfg.configs_topology);
    let mut ex = StepExecutor::new(index.clone(), flags.clone(), &cfg.ir_dir, cfg.targets.as_deref())?;
    let mut ledger = DecisionLedger::default();
    let mut adapter = SubmissionAdapter::new(&index.project);
    let mut failures: Vec<Json> = Vec::new();
    let mut step_requests: IndexMap<String, Vec<StepRequest>> = IndexMap::new();

    for (sid, steps) in &raw {
        let r = catch_unwind(AssertUnwindSafe(|| {
            run_scenario(sid, steps, &index, &catalog, &flags, &mut ex, &mut ledger, &mut failures, &mut step_requests)
        }));
        let err = match r {
            Ok(Ok(sets)) => {
                adapter.add_scenario_edges(sid, &sets.methods, &sets.calls, &sets.remote, &sets.data, Some(&mut evidence));
                continue;
            }
            Ok(Err(e)) => format!("{e:#}"),
            Err(p) => panic_text(p),
        };
        eprintln!("сбой {sid} (сценарий): {err}");
        failures.push(failure(Some(sid), None, "сценарий", &err));
        // Пустой блок лучше отсутствующего: вид рёбер, которого нет и в эталоне, даёт 1 (README организаторов)
        adapter.scenarios.entry(sid.clone()).or_default();
    }

    adapter.save(&cfg.out)?;
    let dir = cfg.out.parent().map(|p| p.to_path_buf()).unwrap_or_default();
    evidence.save(&dir.join("evidence.json"))?;
    let write = |name: &str, v: &Json| -> Result<()> {
        std::fs::write(dir.join(name), dumps_indent1(v)).with_context(|| format!("не записан {name}"))
    };
    write("decisions.json", &ledger.to_json())?;
    write("step_requests.json", &serde_json::to_value(&step_requests)?)?;
    write("m4_unknowns.json", &serde_json::to_value(&ex.core.unknowns)?)?;
    write("exec_failures.json", &Json::Array(failures.clone()))?;
    println!("archonity-exec: сценариев {}, сбоев {}, выдача: {}", raw.len(), failures.len(), cfg.out.display());
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn run_scenario(
    sid: &str,
    steps: &[StepRequest],
    index: &Rc<SkeletonIndex>,
    catalog: &HandlerCatalog,
    flags: &RuleFlags,
    ex: &mut StepExecutor,
    ledger: &mut DecisionLedger,
    failures: &mut Vec<Json>,
    step_requests: &mut IndexMap<String, Vec<StepRequest>>,
) -> Result<StepEdges> {
    ledger.begin_scenario(sid);
    let passenger = resolve_passenger_context(index, sid);
    let mut all = StepEdges::default();
    step_requests.insert(sid.to_string(), Vec::new());
    ex.begin_scenario(sid);

    for raw_req in steps {
        ledger.begin_step(Some(raw_req.step));
        let mut stage = "M1";
        let r = catch_unwind(AssertUnwindSafe(|| {
            run_step(raw_req, index, catalog, flags, ex, ledger, &passenger, &mut stage, step_requests.get_mut(sid).unwrap())
        }));
        let err = match r {
            Ok(Ok(e)) => {
                all.methods.extend(e.methods);
                all.calls.extend(e.calls);
                all.remote.extend(e.remote);
                all.data.extend(e.data);
                continue;
            }
            Ok(Err(e)) => format!("{e:#}"),
            Err(p) => panic_text(p),
        };
        // Р2: шаг со сбоем не даёт рёбер, остальные идут дальше
        eprintln!("сбой {sid}, шаг {} ({stage}): {err}", raw_req.step);
        failures.push(failure(Some(sid), Some(raw_req.step), stage, &err));
    }

    let r19: BTreeSet<String> = all
        .calls
        .iter()
        .chain(&all.remote)
        .chain(&all.data)
        .map(|(s, _)| s.clone())
        .chain(all.calls.iter().chain(&all.remote).map(|(_, t)| t.clone()))
        .collect();
    ledger.begin_step(None);
    for m in r19.difference(&all.methods.clone()) {
        ledger.execute(m, "DEFAULT_RULE", "R19", Default::default())?;
    }
    all.methods.extend(r19);
    Ok(all)
}

#[allow(clippy::too_many_arguments)]
fn run_step(
    raw_req: &StepRequest,
    index: &SkeletonIndex,
    catalog: &HandlerCatalog,
    flags: &RuleFlags,
    ex: &mut StepExecutor,
    ledger: &mut DecisionLedger,
    passenger: &ScenarioContext,
    stage: &mut &'static str,
    requests: &mut Vec<StepRequest>,
) -> Result<StepEdges> {
    let mut req = raw_req.clone();
    // R20: замена после заземления; история шагов в промпте M1 и кеш LLM не меняются
    if flags.unbound_handlers == UnboundHandlers::Rebind {
        if let Some(r) = rebind(index, catalog, &req) {
            req = r;
        }
    }
    requests.push(req.clone());
    *stage = "M4";
    let mut e = ex.run_step(&req, passenger, ledger)?;
    *stage = "M5";
    apply_spring_security(index, &mut e.methods, &mut e.calls, &mut e.data, ledger)?;
    // M5: конструктор в ответе, только если из него исполнился вызов проекта (R7, ADR-006)
    project_constructors(&mut e.methods, &mut e.calls, &mut e.remote, &mut e.data, flags.constructors, ledger)?;
    Ok(e)
}

/// Пассажир из контекста задачи («pre-registered user <имя>»); ID — поле `@Id` сущности `UserDetails` в строке дампа,
/// где есть это имя. Нет пассажира в контексте — предупреждение: имя при входе неизвестно.
pub fn resolve_passenger_context(index: &SkeletonIndex, scenario_id: &str) -> ScenarioContext {
    let user_name = index.context.get("user_name").and_then(Json::as_str).filter(|s| !s.is_empty()).map(str::to_string);
    let Some(user_name) = user_name else {
        eprintln!("контекст задачи не называет пассажира (pre-registered user): имя при входе неизвестно");
        return ScenarioContext { scenario_id: scenario_id.to_string(), ..Default::default() };
    };
    let account_id = principal_id(index, &user_name);
    ScenarioContext { user_name: Some(user_name), account_id, scenario_id: scenario_id.to_string() }
}

/// ID пользователя по таблице сущности `UserDetails` (та же сущность, что у правила Spring Security).
fn principal_id(index: &SkeletonIndex, user_name: &str) -> Option<String> {
    let mut ids: Vec<&String> = index.type_nodes.keys().collect();
    ids.sort();
    for id in ids {
        let n = &index.type_nodes[id];
        if !archonity_io::jx::strs(n, "implements_raw").contains(&"UserDetails") {
            continue;
        }
        let Some(ent) = index.entities.entities.get(archonity_io::jx::str_(n, "fqn").unwrap_or("")) else { continue };
        let (Some(table), Some(id_field)) = (ent.table.as_deref().filter(|t| !t.is_empty()), ent.id_field.as_deref().filter(|f| !f.is_empty())) else {
            continue;
        };
        let col = camel_to_snake(id_field);
        for row in index.db_state.get_table(table) {
            if row.values().any(|v| matches!(v, Value::Str(s) if &**s == user_name)) {
                match row.get(&col) {
                    Some(Value::Null) | None => {}
                    Some(Value::Str(s)) => return Some(s.to_string()),
                    Some(other) => return Some(archonity_model::values::py_str(other)),
                }
            }
        }
    }
    None
}

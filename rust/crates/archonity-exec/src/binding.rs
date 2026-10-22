//! R20 (`engine/grounding/binding.py`, `StepGrounder.rebind`): обработчик, который Spring вызвать не может, — шаг
//! через рабочий обработчик того же контроллера. Вход — шаг до замены.
//!
//! `@PathVariable` связывается по имени; если его нет среди переменных шаблона пути, Spring отвечает ошибкой до
//! вызова контроллера. Замена — обработчик того же класса, который вызвать можно и у которого есть параметр запроса
//! с тем же корнем имени; если такого нет или их несколько — замены нет.

use archonity_io::{jx, SkeletonIndex};
use archonity_model::StepRequest;
use indexmap::IndexMap;
use serde_json::json;

use crate::catalog::HandlerCatalog;

/// Корень имени параметра: `stationNameList`, `stationNames` -> `stationname`.
fn stem(name: &str) -> String {
    let mut s = name;
    for suf in ["List", "Set", "Array"] {
        if let Some(t) = s.strip_suffix(suf) {
            s = t;
            break;
        }
    }
    let mut owned = s.to_string();
    if owned.ends_with('s') && owned.chars().rev().nth(1).is_some_and(|c| c.is_ascii_lowercase()) {
        owned.pop();
    }
    owned.to_lowercase()
}

pub fn rebind(index: &SkeletonIndex, catalog: &HandlerCatalog, req: &StepRequest) -> Option<StepRequest> {
    let h = catalog.handlers.get(&req.handler)?;
    let bad = catalog.unbound_path_variables(h);
    if bad.is_empty() {
        return None;
    }
    let owner = index.n.get(&req.handler).and_then(|n| jx::str_(n, "owner"));
    let want: Vec<String> = bad.iter().map(|v| stem(v)).collect();
    let alts: Vec<&str> = catalog
        .handlers
        .values()
        .filter(|x| {
            x.id != req.handler
                && index.n.get(&x.id).and_then(|n| jx::str_(n, "owner")) == owner
                && catalog.unbound_path_variables(x).is_empty()
                && x.params.iter().any(|(name, src)| matches!(*src, "path" | "query" | "body") && want.contains(&stem(name)))
        })
        .map(|x| x.id.as_str())
        .collect();
    if alts.len() != 1 {
        return None;
    }
    let (verb, path) = catalog.handlers[alts[0]].routes[0].clone();
    let mut grounding = req.grounding.clone();
    grounding.insert("rebound".into(), json!({"rule": "R20:unbound_path_variable", "from": req.handler, "path_variables": bad}));
    let mut out = req.clone();
    out.handler = alts[0].to_string();
    out.http = IndexMap::from([("method".to_string(), verb), ("path".to_string(), path)]);
    out.params = IndexMap::new();
    out.ui_source = None;
    out.body_src = IndexMap::new();
    out.body_groups = Vec::new();
    out.grounding = grounding;
    Some(out)
}

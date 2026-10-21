//! Маршруты и параметры обработчиков (часть `HandlerCatalog` из `engine/grounding/docs.py`, нужная R20).

use std::collections::{BTreeMap, HashMap};

use archonity_io::{jx, SkeletonIndex};
use regex::Regex;

pub struct HandlerInfo {
    pub id: String,
    /// `(глагол, путь)`; глагол `ANY`, если в скелете его нет.
    pub routes: Vec<(String, String)>,
    /// `(имя, источник)`: `body`, `path`, `query`, `header`, `other`.
    pub params: Vec<(String, &'static str)>,
}

pub struct HandlerCatalog {
    /// Обработчики по ID (порядок ID как в Python: `sorted`).
    pub handlers: BTreeMap<String, HandlerInfo>,
    /// Имена, по которым Spring ищет `@PathVariable` метода.
    path_vars: HashMap<String, Vec<String>>,
}

fn param_source(anns: &[serde_json::Value]) -> &'static str {
    let names: Vec<&str> = anns.iter().filter_map(|a| jx::str_(a, "name")).collect();
    for (n, s) in [("RequestBody", "body"), ("PathVariable", "path"), ("RequestParam", "query"), ("RequestHeader", "header")] {
        if names.contains(&n) {
            return s;
        }
    }
    "other"
}

impl HandlerCatalog {
    pub fn build(index: &SkeletonIndex) -> HandlerCatalog {
        let name_arg = Regex::new(r#"(?:^|value\s*=\s*|name\s*=\s*)"(\w+)""#).unwrap();
        let mut params: HashMap<&str, Vec<&serde_json::Value>> = HashMap::new();
        let mut path_vars: HashMap<String, Vec<String>> = HashMap::new();
        for n in index.n.values() {
            if jx::str_(n, "kind") != Some("parameter") {
                continue;
            }
            let Some(method) = jx::str_(n, "method") else { continue };
            params.entry(method).or_default().push(n);
            for a in jx::arr(n, "annotations") {
                if jx::str_(a, "name") == Some("PathVariable") {
                    let args = jx::str_(a, "args").unwrap_or("").trim();
                    let name = name_arg.captures(args).map(|m| m[1].to_string()).unwrap_or_else(|| jx::str_(n, "name").unwrap_or("").to_string());
                    path_vars.entry(method.to_string()).or_default().push(name);
                }
            }
        }
        let mut routes: BTreeMap<&str, Vec<(String, String)>> = BTreeMap::new();
        for (nid, verb, tpl) in &index.handlers {
            let r = (verb.clone().filter(|v| !v.is_empty()).unwrap_or_else(|| "ANY".to_string()), format!("/{}", tpl.join("/")));
            let rs = routes.entry(nid.as_str()).or_default();
            if !rs.contains(&r) {
                rs.push(r);
            }
        }
        let handlers = routes
            .into_iter()
            .map(|(nid, rs)| {
                let mut ps: Vec<&serde_json::Value> = params.get(nid).cloned().unwrap_or_default();
                ps.sort_by_key(|p| jx::int(p, "index").unwrap_or(0));
                let ps = ps.iter().map(|p| (jx::str_(p, "name").unwrap_or("").to_string(), param_source(jx::arr(p, "annotations")))).collect();
                (nid.to_string(), HandlerInfo { id: nid.to_string(), routes: rs, params: ps })
            })
            .collect();
        HandlerCatalog { handlers, path_vars }
    }

    /// `@PathVariable` обработчика, которых нет в шаблоне пути ни одного его маршрута.
    pub fn unbound_path_variables(&self, h: &HandlerInfo) -> Vec<String> {
        let var = Regex::new(r"\{(\w+)").unwrap();
        let tpl: Vec<String> = h.routes.iter().flat_map(|(_, p)| var.captures_iter(p).map(|m| m[1].to_string()).collect::<Vec<_>>()).collect();
        self.path_vars.get(&h.id).map(|v| v.iter().filter(|x| !tpl.contains(x)).cloned().collect()).unwrap_or_default()
    }
}

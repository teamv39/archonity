//! `evidence.json` (`engine/evidence.py`): доказательства рёбер `remote`, `data` и маршрутов шлюза.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use anyhow::Result;
use indexmap::IndexMap;
use serde_json::{json, Value as Json};

use archonity_model::pyfmt::splitlines;

use crate::json_py::dumps_indent;
use crate::jx;
use crate::skeleton::SkeletonIndex;

pub struct EvidenceLogger<'a> {
    index: &'a SkeletonIndex,
    targets_root: Option<PathBuf>,
    evidence: IndexMap<String, Json>,
    gateway_routes: IndexMap<String, Json>,
    /// Шлюз Spring Cloud Gateway из `facts/configs_topology.json`; без файла маршрутов шлюза нет.
    pub gateway: Option<String>,
    gateway_config_source: String,
    file_cache: HashMap<PathBuf, Vec<String>>,
}

impl<'a> EvidenceLogger<'a> {
    /// `configs_topology` — `facts/configs_topology.json`; нет файла — шлюза нет.
    pub fn new(index: &'a SkeletonIndex, targets_root: Option<&Path>, configs_topology: &Path) -> EvidenceLogger<'a> {
        let mut ev = EvidenceLogger {
            index,
            targets_root: targets_root.map(Path::to_path_buf),
            evidence: IndexMap::new(),
            gateway_routes: IndexMap::new(),
            gateway: None,
            gateway_config_source: String::new(),
            file_cache: HashMap::new(),
        };
        let data: Option<Json> = std::fs::read_to_string(configs_topology).ok().and_then(|t| serde_json::from_str(&t).ok());
        if let Some(scg) = data.as_ref().and_then(|d| d.get("gateway_routes")).and_then(|g| g.get("spring_cloud_gateway")) {
            ev.gateway = jx::str_(scg, "service_name").filter(|s| !s.is_empty()).map(str::to_string);
            if let Some(src) = jx::str_(scg, "config_source").filter(|s| !s.is_empty()) {
                ev.gateway_config_source = src.to_string();
            }
            for r in jx::arr(scg, "routes") {
                if let Some(id) = jx::str_(r, "id").filter(|s| !s.is_empty()) {
                    ev.gateway_routes.insert(id.to_string(), r.clone());
                }
            }
        }
        ev
    }

    /// Сниппет исходника вокруг строки `line` (±`context`), с кешем файлов.
    fn extract_snippet(&mut self, file_rel: &str, line: i64, context: i64) -> String {
        let Some(root) = &self.targets_root else { return String::new() };
        if file_rel.is_empty() || line <= 0 {
            return String::new();
        }
        let full = root.join(file_rel);
        if !self.file_cache.contains_key(&full) {
            if !full.is_file() {
                return String::new();
            }
            let Ok(bytes) = std::fs::read(&full) else { return String::new() };
            let text = String::from_utf8_lossy(&bytes);
            self.file_cache.insert(full.clone(), splitlines(&text).into_iter().map(str::to_string).collect());
        }
        let lines = &self.file_cache[&full];
        let start = (line - 1 - context).max(0) as usize;
        let end = ((line + context) as usize).min(lines.len());
        if start >= end {
            return String::new();
        }
        lines[start..end].join("\n")
    }

    fn has_snippet(&self, edge_id: &str) -> bool {
        self.evidence
            .get(edge_id)
            .and_then(|e| e.get("evidence_details"))
            .and_then(|d| d.get("code_snippet"))
            .is_some_and(|s| s.as_str().is_some_and(|s| !s.is_empty()))
    }

    fn service_of(m: &str) -> String {
        if m.starts_with("method:") {
            m.split(':').nth(1).unwrap_or("").to_string()
        } else {
            m.to_string()
        }
    }

    /// Доказательство межсервисного вызова `remote`.
    pub fn record_remote_call(&mut self, src: &str, tgt: &str) -> String {
        let (svc_src, svc_tgt) = (Self::service_of(src), Self::service_of(tgt));
        let edge_id = format!("{svc_src}->{svc_tgt}:REST_HTTP");
        if self.has_snippet(&edge_id) {
            return edge_id;
        }
        let node = self.index.n.get(src);
        let file = node.and_then(|n| jx::str_(n, "file")).unwrap_or("").to_string();
        let line = node.and_then(|n| jx::int(n, "line")).unwrap_or(0);
        let snippet = self.extract_snippet(&file, line, 2);
        let snippet = if snippet.is_empty() { format!("// AST call from {src} to {tgt}") } else { snippet };
        self.evidence.insert(
            edge_id.clone(),
            json!({
                "edge_id": edge_id, "source": svc_src, "target": svc_tgt, "relation_type": "REST_HTTP",
                "source_type": "AST_EXACT", "confidence": 1.0,
                "evidence_details": {
                    "file_path": file, "line_number": line, "caller": src, "matched_endpoint": tgt,
                    "call_chain": [src, tgt], "code_snippet": snippet, "is_reachable": true,
                },
            }),
        );
        edge_id
    }

    /// Доказательство обращения к таблице БД.
    pub fn record_data_access(&mut self, src: &str, table: &str) -> String {
        let svc_src = Self::service_of(src);
        let db_name = if table.starts_with("res:table:") { table.splitn(3, ':').nth(2).unwrap_or("") } else { table };
        let db_node = format!("db-{}", db_name.replace('.', "-"));
        let edge_id = format!("{svc_src}->{db_node}:DATABASE");
        if self.has_snippet(&edge_id) {
            return edge_id;
        }
        let node = self.index.n.get(src);
        let mut file = node.and_then(|n| jx::str_(n, "file")).unwrap_or("").to_string();
        let mut line = node.and_then(|n| jx::int(n, "line")).unwrap_or(0);
        if file.is_empty() {
            // Сущность таблицы в скелете, если у метода нет файла
            let origin = self.index.n.get(table).and_then(|t| jx::arr(t, "origin").first());
            if let Some(o) = origin {
                file = jx::str_(o, "file").unwrap_or("").to_string();
                line = jx::int(o, "line").unwrap_or(0);
            }
        }
        let snippet = self.extract_snippet(&file, line, 2);
        let snippet = if snippet.is_empty() { format!("// Database table access: {table}") } else { snippet };
        self.evidence.insert(
            edge_id.clone(),
            json!({
                "edge_id": edge_id, "source": svc_src, "target": db_node, "relation_type": "DATABASE",
                "source_type": "AST_EXACT", "confidence": 1.0,
                "evidence_details": {
                    "file_path": file, "line_number": line, "caller": src, "matched_endpoint": table,
                    "call_chain": [src, table], "code_snippet": snippet, "is_reachable": true,
                },
            }),
        );
        edge_id
    }

    /// Маршрут шлюза к сервису: только сервисы с маршрутом (не библиотеки) и не сам шлюз.
    pub fn record_gateway_route(&mut self, target_service: &str) -> String {
        let Some(gw) = self.gateway.clone() else { return String::new() };
        if !self.gateway_routes.contains_key(target_service) || target_service == gw {
            return String::new();
        }
        let edge_id = format!("{gw}->{target_service}:REST_HTTP");
        if self.evidence.contains_key(&edge_id) {
            return edge_id;
        }
        let route = &self.gateway_routes[target_service];
        let preds: Vec<&str> = jx::arr(route, "predicates").iter().filter_map(Json::as_str).collect();
        let pred = if preds.is_empty() { format!("Path=/api/v1/{target_service}/**") } else { preds.join(", ") };
        self.evidence.insert(
            edge_id.clone(),
            json!({
                "edge_id": edge_id, "source": gw, "target": target_service, "relation_type": "REST_HTTP",
                "source_type": "CONFIG", "confidence": 1.0,
                "evidence_details": {
                    "file_path": self.gateway_config_source, "line_number": 20,
                    "caller": "org.springframework.cloud.gateway.route.RouteDefinitionRouteLocator",
                    "matched_endpoint": pred, "call_chain": [gw, target_service],
                    "code_snippet": format!("- id: {target_service}\n  predicates:\n    - {pred}"),
                    "config_key": format!("spring.cloud.gateway.routes[{target_service}]"), "is_reachable": true,
                },
            }),
        );
        edge_id
    }

    /// Тело `evidence.json`: по `edge_id` по возрастанию.
    pub fn to_json(&self) -> Json {
        let mut keys: Vec<&String> = self.evidence.keys().collect();
        keys.sort();
        Json::Object(keys.into_iter().map(|k| (k.clone(), self.evidence[k].clone())).collect())
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        std::fs::write(path, dumps_indent(&self.to_json(), 2))?;
        Ok(())
    }
}

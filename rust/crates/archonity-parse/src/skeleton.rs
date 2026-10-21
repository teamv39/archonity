//! Узлы скелета, которые нужны разбору: методы (ID берём дословно), call_site по `(file, line, col)`,
//! анонимные типы по `(file, line)` и зависимости модулей (рёбра `depends_on`).

use std::collections::{BTreeSet, HashMap, HashSet};
use std::fs::File;
use std::io::{BufReader, Read};
use std::path::Path;

use anyhow::{Context, Result};
use flate2::read::GzDecoder;
use serde_json::Value as Json;

/// Узел метода скелета. `owner` — FQN типа-владельца без префикса `type:<module>:`.
#[derive(Debug, Clone)]
pub struct MethodNode {
    pub id: String,
    pub name: String,
    pub owner: String,
    pub module: String,
    pub param_count: usize,
    pub file: String,
    pub line: i64,
    pub end: i64,
    pub is_abstract: bool,
}

#[derive(Default)]
pub struct Skeleton {
    call_site_by_pos: HashMap<(String, i64, i64), String>,
    methods_by_file: HashMap<String, Vec<usize>>,
    methods_by_owner: HashMap<String, Vec<usize>>,
    anonymous_type_by_pos: HashMap<(String, i64), String>,
    call_sites_by_method: HashMap<String, BTreeSet<String>>,
    pub methods: Vec<MethodNode>,
    call_sites_with_edges: HashSet<String>,
    /// Модуль -> модули, классы которых он видит (`depends_on`), в порядке рёбер.
    depends_on: HashMap<String, Vec<String>>,
    /// Общие библиотеки проекта: модули, от которых зависят другие.
    shared: BTreeSet<String>,
}

fn s<'a>(v: &'a Json, k: &str) -> &'a str {
    v.get(k).and_then(Json::as_str).unwrap_or("")
}

fn i(v: &Json, k: &str) -> i64 {
    v.get(k).and_then(Json::as_i64).unwrap_or(0)
}

impl Skeleton {
    /// Скелет `.json.gz` или `.json`.
    pub fn load(path: &Path) -> Result<Skeleton> {
        let f = File::open(path).with_context(|| format!("скелет {}", path.display()))?;
        let mut raw = Vec::new();
        if path.extension().is_some_and(|e| e == "gz") {
            GzDecoder::new(BufReader::new(f)).read_to_end(&mut raw)?;
        } else {
            BufReader::new(f).read_to_end(&mut raw)?;
        }
        let root: Json = serde_json::from_slice(&raw).context("скелет не JSON")?;
        Ok(Skeleton::from_json(&root))
    }

    pub fn from_json(root: &Json) -> Skeleton {
        let mut sk = Skeleton::default();
        if let Some(nodes) = root.get("nodes").and_then(Json::as_object) {
            for (id, n) in nodes {
                match s(n, "kind") {
                    "call_site" => {
                        sk.call_site_by_pos.insert((s(n, "file").to_string(), i(n, "line"), i(n, "col")), id.clone());
                        sk.call_sites_by_method.entry(s(n, "method").to_string()).or_default().insert(id.clone());
                    }
                    "method" => {
                        let owner = s(n, "owner");
                        let owner_fqn = owner.splitn(3, ':').nth(2).unwrap_or("").to_string();
                        let m = MethodNode {
                            id: id.clone(),
                            name: s(n, "name").to_string(),
                            owner: owner_fqn.clone(),
                            module: s(n, "module").to_string(),
                            param_count: n.get("params_as_written").and_then(Json::as_array).map_or(0, Vec::len),
                            file: s(n, "file").to_string(),
                            line: i(n, "line"),
                            end: i(n, "end"),
                            is_abstract: n.get("abstract").and_then(Json::as_bool).unwrap_or(false),
                        };
                        let idx = sk.methods.len();
                        sk.methods_by_file.entry(m.file.clone()).or_default().push(idx);
                        sk.methods_by_owner.entry(owner_fqn).or_default().push(idx);
                        sk.methods.push(m);
                    }
                    "type" => {
                        if s(n, "type_kind") == "anonymous" {
                            sk.anonymous_type_by_pos.insert((s(n, "file").to_string(), i(n, "line")), id.clone());
                        }
                    }
                    _ => {}
                }
            }
        }
        if let Some(edges) = root.get("edges").and_then(Json::as_array) {
            for e in edges {
                let src = s(e, "source");
                if src.starts_with("call:") {
                    sk.call_sites_with_edges.insert(src.to_string());
                } else if s(e, "type") == "depends_on" {
                    let target = s(e, "target").strip_prefix("module:").unwrap_or(s(e, "target")).to_string();
                    let from = src.strip_prefix("module:").unwrap_or(src).to_string();
                    sk.depends_on.entry(from).or_default().push(target.clone());
                    sk.shared.insert(target);
                }
            }
        }
        sk
    }

    /// Модули, где ищется тип по простому имени после модуля вызывающего: зависимости, а без них — общие библиотеки.
    pub fn dependencies(&self, module: &str) -> Vec<String> {
        match self.depends_on.get(module) {
            Some(d) if !d.is_empty() => d.clone(),
            _ => self.shared.iter().cloned().collect(),
        }
    }

    pub fn shared_modules(&self) -> &BTreeSet<String> {
        &self.shared
    }

    /// ID call_site по позиции вызова.
    pub fn call_site(&self, file: &str, line: usize, col: usize) -> Option<&str> {
        self.call_site_by_pos.get(&(file.to_string(), line as i64, col as i64)).map(String::as_str)
    }

    /// ID анонимного типа, объявленного в строке.
    pub fn anonymous_type(&self, file: &str, line: usize) -> Option<&str> {
        self.anonymous_type_by_pos.get(&(file.to_string(), line as i64)).map(String::as_str)
    }

    pub fn methods_in_file(&self, file: &str) -> Vec<&MethodNode> {
        self.methods_by_file.get(file).map(|v| v.iter().map(|&k| &self.methods[k]).collect()).unwrap_or_default()
    }

    pub fn has_file(&self, file: &str) -> bool {
        self.methods_by_file.get(file).is_some_and(|v| !v.is_empty())
    }

    /// Метод типа по имени и числу аргументов, если он единственный.
    pub fn unique_method(&self, owner: &str, name: &str, arg_count: usize) -> Option<&MethodNode> {
        let mut found = None;
        for &k in self.methods_by_owner.get(owner)? {
            let m = &self.methods[k];
            if m.name == name && m.param_count == arg_count {
                if found.is_some() {
                    return None;
                }
                found = Some(m);
            }
        }
        found
    }

    /// Есть ли у call_site исходящие рёбра (`calls`, `runtime_dispatch`, `remote_call`, `data_access`...).
    pub fn has_edges(&self, call_site: &str) -> bool {
        self.call_sites_with_edges.contains(call_site)
    }

    pub fn call_sites_of(&self, method_id: &str) -> BTreeSet<String> {
        self.call_sites_by_method.get(method_id).cloned().unwrap_or_default()
    }
}

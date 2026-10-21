//! IR тел всех методов скелета (`archparse/README.md`, раздел 3.6): файл `<module>.json` на модуль.
//! Заодно считает покрытие: каждый метод скелета с телом найден, каждый call_site встретился один раз.

use std::collections::{BTreeMap, BTreeSet, HashSet};

use serde_json::{Map, Value as Json};
use tree_sitter::Node;

use crate::ast::{self, field, line, Doc};
use crate::body::BodyBuilder;
use crate::index::ProjectIndex;
use crate::skeleton::{MethodNode, Skeleton};

pub const SCHEMA: &str = "method_ir/1";

#[derive(Default)]
pub struct Bodies {
    pub modules: BTreeMap<String, Json>,
    pub methods: usize,
    pub ir_calls: usize,
    pub call_sites: usize,
    pub missing_methods: Vec<String>,
    pub unmatched_declarations: Vec<String>,
    pub uncovered_call_sites: Vec<String>,
    pub duplicate_call_sites: Vec<String>,
    pub foreign_call_sites: Vec<String>,
}

pub fn build(sk: &Skeleton, docs: &[Doc]) -> Bodies {
    let mut project = ProjectIndex::new(sk);
    for d in docs {
        project.add(d);
    }
    let mut r = Bodies::default();
    let mut by_module: BTreeMap<String, BTreeMap<String, Json>> = BTreeMap::new();
    let mut matched: HashSet<String> = HashSet::new();
    for doc in docs {
        if !sk.has_file(&doc.rel) {
            continue; // файл вне модулей скелета
        }
        for decl in ast::descendants(doc.root()).into_iter().filter(|n| ast::is_callable(n.kind())) {
            let Some(body) = body_of(decl) else { continue };
            let Some(node) = match_decl(sk, doc, decl) else {
                r.unmatched_declarations.push(format!("{}:{} {}", doc.rel, line(decl), doc.ftext(decl, "name")));
                continue;
            };
            matched.insert(node.id.clone());
            let mut b = BodyBuilder::new(sk, &project, doc, node, decl);
            let ir = b.build(decl, body);
            by_module.entry(node.module.clone()).or_default().insert(node.id.clone(), ir);
            r.methods += 1;
            r.ir_calls += b.ir_calls;
            coverage(&mut r, sk, node, &b.call_sites_seen);
        }
    }
    for m in &sk.methods {
        if !m.is_abstract && !matched.contains(&m.id) {
            r.missing_methods.push(m.id.clone());
        }
    }
    for (module, methods) in by_module {
        let mut doc = Map::new();
        doc.insert("schema".into(), SCHEMA.into());
        doc.insert("module".into(), module.clone().into());
        doc.insert("methods".into(), Json::Object(methods.into_iter().collect()));
        r.modules.insert(module, Json::Object(doc));
    }
    r
}

fn coverage(r: &mut Bodies, sk: &Skeleton, node: &MethodNode, seen: &[String]) {
    let expected = sk.call_sites_of(&node.id);
    let mut uniq: BTreeSet<&str> = BTreeSet::new();
    for cs in seen {
        if !uniq.insert(cs) {
            r.duplicate_call_sites.push(cs.clone());
        } else if !expected.contains(cs) {
            r.foreign_call_sites.push(cs.clone());
        }
    }
    r.call_sites += uniq.len();
    for cs in &expected {
        if !uniq.contains(cs.as_str()) {
            r.uncovered_call_sites.push(cs.clone());
        }
    }
}

fn body_of(decl: Node) -> Option<Node> {
    field(decl, "body")
}

/// Метод скелета: тот же файл, имя, число параметров, строка объявления между началом (с аннотациями) и именем.
fn match_decl<'s>(sk: &'s Skeleton, doc: &Doc, decl: Node) -> Option<&'s MethodNode> {
    let ctor = decl.kind() == "constructor_declaration";
    let name = if ctor { "<init>" } else { doc.ftext(decl, "name") };
    let from = line(decl) as i64;
    let to = line(field(decl, "name")?) as i64;
    let params = ast::parameter_nodes(decl).len();
    let mut found = None;
    for m in sk.methods_in_file(&doc.rel) {
        if !m.is_abstract && m.name == name && m.param_count == params && m.line >= from && m.line <= to {
            if found.is_some() {
                return None;
            }
            found = Some(m);
        }
    }
    found
}

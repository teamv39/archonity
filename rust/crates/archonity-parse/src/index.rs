//! Индекс всего проекта для IR тел методов: типы по простому имени, константы enum с аргументами из объявления,
//! поля `static final` с литералом (порт `ProjectIndex`).

use std::collections::HashMap;

use indexmap::IndexMap;
use serde_json::{json, Value as Json};

use crate::ast::{self, Doc};
use crate::lit::{const_value, is_literal};
use crate::skeleton::Skeleton;

/// Тип проекта: FQN как в скелете (вложенные через `$`), модуль, пакет.
#[derive(Clone)]
pub struct TypeInfo {
    pub fqn: String,
    pub module: String,
    pub pkg: String,
}

pub struct ProjectIndex<'s> {
    skeleton: &'s Skeleton,
    types_by_simple: HashMap<String, Vec<TypeInfo>>,
    /// enum -> константа -> аргументы объявления уже в виде IR (`lit` или `text`).
    enum_constants: HashMap<String, IndexMap<String, Vec<Json>>>,
    /// тип -> поле -> значение литерала.
    constants: HashMap<String, HashMap<String, Json>>,
}

impl<'s> ProjectIndex<'s> {
    pub fn new(skeleton: &'s Skeleton) -> Self {
        ProjectIndex { skeleton, types_by_simple: HashMap::new(), enum_constants: HashMap::new(), constants: HashMap::new() }
    }

    /// Добавляет все типы файла.
    pub fn add(&mut self, doc: &Doc) {
        for td in ast::descendants(doc.root()).into_iter().filter(|n| ast::is_type_decl(n.kind())) {
            let fqn = ast::binary_name(doc, td);
            let simple = doc.ftext(td, "name").to_string();
            self.types_by_simple.entry(simple).or_default().push(TypeInfo { fqn: fqn.clone(), module: doc.module.clone(), pkg: doc.pkg.clone() });
            if td.kind() == "enum_declaration" {
                let mut cs = IndexMap::new();
                if let Some(body) = ast::field(td, "body") {
                    for c in ast::kids(body).into_iter().filter(|c| c.kind() == "enum_constant") {
                        let args = ast::argument_nodes(c)
                            .into_iter()
                            .map(|a| if is_literal(a) { const_value(doc, a) } else { json!({"text": ast::expr_str(doc, a)}) })
                            .collect();
                        cs.insert(doc.ftext(c, "name").to_string(), args);
                    }
                }
                self.enum_constants.insert(fqn.clone(), cs);
            }
            let iface = td.kind() == "interface_declaration";
            for fd in ast::field_decls(td) {
                if !(iface || (ast::has_modifier(fd, "static") && ast::has_modifier(fd, "final"))) {
                    continue;
                }
                for vd in ast::declarators(fd) {
                    if let Some(init) = ast::field(vd, "value").filter(|i| is_literal(*i)) {
                        self.constants.entry(fqn.clone()).or_default().insert(doc.ftext(vd, "name").to_string(), const_value(doc, init));
                    }
                }
            }
        }
    }

    /// FQN типа проекта по простому имени из файла: явный импорт, тот же пакет, `*`-импорт, тот же модуль,
    /// модули, от которых он зависит. `None` — тип не из проекта.
    pub fn resolve_type(&self, simple: &str, doc: &Doc) -> Option<String> {
        let cands = self.types_by_simple.get(simple)?;
        let suffix = format!(".{simple}");
        for imp in &doc.imports {
            if !imp.is_static && !imp.asterisk && imp.name.ends_with(&suffix) {
                for t in cands {
                    if t.fqn.replace('$', ".") == imp.name {
                        return Some(t.fqn.clone());
                    }
                }
                return None; // импортирован тип не из проекта
            }
        }
        if let Some(t) = cands.iter().find(|t| t.pkg == doc.pkg && t.module == doc.module) {
            return Some(t.fqn.clone());
        }
        for imp in &doc.imports {
            if !imp.is_static && imp.asterisk {
                if let Some(t) = cands.iter().find(|t| t.pkg == imp.name) {
                    return Some(t.fqn.clone());
                }
            }
        }
        if let Some(t) = cands.iter().find(|t| t.module == doc.module) {
            return Some(t.fqn.clone());
        }
        for dep in self.skeleton.dependencies(&doc.module) {
            if let Some(t) = cands.iter().find(|t| t.module == dep) {
                return Some(t.fqn.clone());
            }
        }
        None
    }

    /// Аргументы константы enum в объявлении или `None`, если такой константы нет.
    pub fn enum_constant(&self, enum_fqn: &str, constant: &str) -> Option<&Vec<Json>> {
        self.enum_constants.get(enum_fqn)?.get(constant)
    }

    /// Enum, в котором константа с таким именем единственная (метки `case` без квалификатора).
    pub fn unique_enum_of(&self, constant: &str) -> Option<&str> {
        let mut found = None;
        for (fqn, cs) in &self.enum_constants {
            if cs.contains_key(constant) {
                if found.is_some() {
                    return None;
                }
                found = Some(fqn.as_str());
            }
        }
        found
    }

    /// Литерал `static final` поля типа.
    pub fn constant(&self, type_fqn: &str, field: &str) -> Option<&Json> {
        self.constants.get(type_fqn)?.get(field)
    }
}

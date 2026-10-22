//! Резолвер констант перечислений для вызовов в конструкторах (порт `EnumResolver`).
//!
//! Повторяет поведение оригинала, включая то, что перечисления регистрируются несколько раз
//! (общий обход `.java` проекта, затем разбор `src/main/java`): список кандидатов по простому имени содержит дубли,
//! поэтому при неоднозначности берётся кандидат из общей библиотеки, а иначе первый.

use std::collections::{BTreeSet, HashMap, HashSet};

use indexmap::IndexMap;

use tree_sitter::Node;

use crate::ast::{self, Doc};

#[derive(Default)]
pub struct EnumIndex {
    constants: IndexMap<String, HashSet<String>>,
    /// Все ключи `constants` в порядке первой регистрации: оригинал перебирает `ConcurrentHashMap`, порядок значения не имеет.
    by_simple: HashMap<String, Vec<String>>,
    module_of: HashMap<String, String>,
    shared: BTreeSet<String>,
}

pub struct EnumConst {
    pub type_fqn: String,
    pub constant: String,
}

impl EnumIndex {
    pub fn new(shared: &BTreeSet<String>) -> Self {
        EnumIndex { shared: shared.clone(), ..Default::default() }
    }

    fn register(&mut self, fqn: &str, constants: HashSet<String>) {
        self.constants.insert(fqn.to_string(), constants);
        let simple = fqn.rsplit('.').next().unwrap_or(fqn).replace('$', ".");
        if simple.contains('.') {
            let short = simple.rsplit('.').next().unwrap_or(&simple).to_string();
            self.by_simple.entry(short).or_default().push(fqn.to_string());
        }
        self.by_simple.entry(simple).or_default().push(fqn.to_string());
    }

    /// Регистрирует перечисления файла; возвращает их FQN.
    pub fn index_doc(&mut self, doc: &Doc) -> Vec<String> {
        let mut out = Vec::new();
        for ed in ast::descendants(doc.root()).into_iter().filter(|n| n.kind() == "enum_declaration") {
            let fqn = ast::binary_name(doc, ed);
            let mut cs = HashSet::new();
            if let Some(body) = ast::field(ed, "body") {
                for c in ast::kids(body).into_iter().filter(|c| c.kind() == "enum_constant") {
                    cs.insert(doc.ftext(c, "name").to_string());
                }
            }
            self.register(&fqn, cs);
            out.push(fqn);
        }
        out
    }

    /// Общий обход проекта (`scanEnums`): модуль перечисления — первый каталог пути.
    pub fn scan_doc(&mut self, doc: &Doc) {
        let module = doc.rel.split('/').next().unwrap_or("").to_string();
        for fqn in self.index_doc(doc) {
            self.module_of.insert(fqn, module.clone());
        }
    }

    fn has_const(&self, enum_fqn: &str, c: &str) -> bool {
        self.constants.get(enum_fqn).is_some_and(|s| s.contains(c))
    }

    /// Вызов на enum-константе: `Type.CONST.m()` или `CONST.m()` со статическим импортом.
    pub fn resolve_call(&mut self, doc: &Doc, call: Node) -> Option<EnumConst> {
        let scope = ast::field(call, "object")?;
        self.resolve_expression(doc, scope)
    }

    pub fn resolve_expression(&mut self, doc: &Doc, expr: Node) -> Option<EnumConst> {
        // оригинал заново регистрирует перечисления файла
        self.index_doc(doc);
        match expr.kind() {
            "field_access" => {
                let name = doc.ftext(expr, "field");
                let scope = ast::field(expr, "object").map(|o| ast::expr_str(doc, o)).unwrap_or_default();
                let enum_fqn = self.resolve_enum_fqn(&scope, doc)?;
                self.has_const(&enum_fqn, name).then(|| EnumConst { type_fqn: enum_fqn, constant: name.to_string() })
            }
            "identifier" => {
                let name = doc.text(expr);
                let enum_fqn = self.resolve_static_import_enum(name, doc)?;
                self.has_const(&enum_fqn, name).then(|| EnumConst { type_fqn: enum_fqn, constant: name.to_string() })
            }
            _ => None,
        }
    }

    fn resolve_enum_fqn(&self, scope: &str, doc: &Doc) -> Option<String> {
        if self.constants.contains_key(scope) {
            return Some(scope.to_string());
        }
        // 1. явные импорты
        let suffix = format!(".{scope}");
        for imp in &doc.imports {
            if !imp.is_static && !imp.asterisk && imp.name.ends_with(&suffix) {
                if self.constants.contains_key(&imp.name) {
                    return Some(imp.name.clone());
                }
                if let Some(f) = self.constants.keys().find(|f| f.replace('$', ".") == imp.name) {
                    return Some(f.clone());
                }
            }
        }
        // 2. текущий пакет
        let local = if doc.pkg.is_empty() { scope.to_string() } else { format!("{}.{scope}", doc.pkg) };
        if self.constants.contains_key(&local) {
            return Some(local);
        }
        // 3. импорты со звёздочкой
        for imp in &doc.imports {
            if !imp.is_static && imp.asterisk {
                let cand = format!("{}.{scope}", imp.name);
                if self.constants.contains_key(&cand) {
                    return Some(cand);
                }
                if let Some(f) = self.constants.keys().find(|f| f.replace('$', ".") == cand) {
                    return Some(f.clone());
                }
            }
        }
        // 4. по простому имени
        let cands = self.by_simple.get(scope)?;
        if cands.is_empty() {
            return None;
        }
        if cands.len() == 1 {
            return Some(cands[0].clone());
        }
        for c in cands {
            if self.module_of.get(c).is_some_and(|m| self.shared.contains(m)) {
                return Some(c.clone());
            }
        }
        Some(cands[0].clone())
    }

    fn resolve_static_import_enum(&self, name: &str, doc: &Doc) -> Option<String> {
        for imp in doc.imports.iter().filter(|i| i.is_static) {
            if imp.asterisk {
                if self.constants.contains_key(&imp.name) && self.has_const(&imp.name, name) {
                    return Some(imp.name.clone());
                }
            } else if imp.name.ends_with(&format!(".{name}")) {
                let enum_fqn = &imp.name[..imp.name.rfind('.').unwrap()];
                if self.constants.contains_key(enum_fqn) {
                    return Some(enum_fqn.to_string());
                }
            }
        }
        None
    }
}

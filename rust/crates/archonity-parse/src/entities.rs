//! Сканер сущностей JPA и вызовов репозиториев Spring Data по всему проекту (порт `EntityScanner`).
//!
//! Даёт движку факты для правила R7 (конструктор сущности при загрузке строк Hibernate): какой сущности принадлежит
//! вызов репозитория, читает он или пишет, ждёт ли успешный путь метода найденную строку или её отсутствие, и что делает
//! конструктор без аргументов. Для правила R10 — коллекции сущностей в отдельных таблицах и какие ленивые коллекции
//! метод загружает сам. Таблицы, данные и решения — на стороне движка.

use std::collections::{BTreeMap, HashMap, HashSet};

use indexmap::IndexMap;
use serde_json::{json, Map, Value as Json};
use tree_sitter::Node;

use crate::ast::{self, argument_nodes, col, expr_str, field, kids, line, Doc};
use crate::enumres::EnumIndex;
use crate::expect::{self, before, enclosing_body};
use crate::skeleton::Skeleton;

type Obj = Map<String, Json>;

const SPRING_DATA_REPOSITORIES: [&str; 5] = ["Repository", "CrudRepository", "JpaRepository", "PagingAndSortingRepository", "MongoRepository"];
const ENTITY_ANNOTATIONS: [&str; 3] = ["Entity", "Embeddable", "Document"];
const COLLECTION_TYPES: [&str; 8] = ["List", "ArrayList", "Set", "HashSet", "Collection", "Map", "HashMap", "LinkedList"];
const EQUALITY_LOOKUPS: [&str; 4] = ["contains", "indexOf", "lastIndexOf", "remove"];

struct RepoInfo<'a> {
    module: String,
    name: String,
    entity_simple: String,
    doc: &'a Doc,
    modifying: HashSet<String>,
}

struct CollectionField {
    field: String,
    table: String,
    fetch: &'static str,
}

struct Entity {
    type_: String,
    module: String,
    file: String,
    kind: String,
    table: Option<String>,
    id_field: Option<String>,
    id_generated: bool,
    no_arg_ctor: Option<String>,
    ctor_statements: usize,
    ctor_assigns_id: bool,
    embedded: Vec<String>,
    collections: Vec<CollectionField>,
}

struct EntityDecl<'a> {
    ir: Entity,
    cid: Node<'a>,
    doc: &'a Doc,
}

/// Тип переменной метода: имя без обобщений и аргумент `Optional<...>`.
struct VarType {
    base: String,
    optional_of: Option<String>,
}

struct RepoCall {
    file: String,
    line: usize,
    col: usize,
    callee: String,
    repository: String,
    entity: Option<String>,
    operation: &'static str,
    expects: Option<&'static str>,
    expects_reason: Option<String>,
    id_assigned: Option<bool>,
    id_assigned_reason: Option<String>,
    collections_loaded: Option<Vec<String>>,
    collections_loaded_reason: Option<Vec<String>>,
    element_callbacks: Option<Vec<(String, String, usize, usize)>>,
}

pub struct Report {
    pub entities: usize,
    pub repository_calls: usize,
    pub constructors: usize,
    pub json: Json,
}

/// Простое имя без пакета и обобщений: `java.util.List<String>` -> `List`.
pub fn base_name(t: &str) -> String {
    let t = t.split('<').next().unwrap_or(t).trim();
    t.rsplit('.').next().unwrap_or(t).to_string()
}

fn simple_name(fqn: &str) -> &str {
    let s = fqn.rsplit('.').next().unwrap_or(fqn);
    s.rsplit('$').next().unwrap_or(s)
}

/// CamelCase -> snake_case по правилу Spring Boot: `_` между строчной, заглавной и строчной буквой.
pub fn spring_physical_name(name: &str) -> String {
    let mut sb: Vec<char> = name.chars().collect();
    let mut i = 1;
    while i + 1 < sb.len() {
        if sb[i - 1].is_lowercase() && sb[i].is_uppercase() && sb[i + 1].is_lowercase() {
            sb.insert(i, '_');
            i += 1;
        }
        i += 1;
    }
    sb.iter().collect::<String>().to_lowercase()
}

fn is_class(kind: &str) -> bool {
    ast::is_class_or_interface(kind)
}

fn entity_binary_name(doc: &Doc, cid: Node) -> String {
    ast::binary_name_where(doc, cid, is_class)
}

fn member_methods<'a>(td: Node<'a>) -> Vec<Node<'a>> {
    ast::members(td).into_iter().filter(|m| m.kind() == "method_declaration").collect()
}

fn constructors<'a>(td: Node<'a>) -> Vec<Node<'a>> {
    ast::members(td).into_iter().filter(|m| m.kind() == "constructor_declaration").collect()
}

fn no_arg_constructor<'a>(cid: Node<'a>) -> Option<Node<'a>> {
    constructors(cid).into_iter().find(|c| ast::parameter_nodes(*c).is_empty())
}

/// Число операторов тела (`BlockStmt.getStatements().size()`): пустой оператор `;` тоже оператор.
fn statement_count(body: Node) -> usize {
    let mut w = body.walk();
    body.children(&mut w).filter(|c| (c.is_named() && !ast::is_comment(*c)) || c.kind() == ";").count()
}

fn element_type_text(doc: &Doc, fd: Node) -> String {
    let Some(t) = field(fd, "type") else { return String::new() };
    let t = if t.kind() == "array_type" { field(t, "element").unwrap_or(t) } else { t };
    ast::type_str(doc, t)
}

fn annotation_names(doc: &Doc, decl: Node) -> Vec<String> {
    ast::annotations(doc, decl).into_iter().map(|(n, _)| n).collect()
}

fn has_annotation(doc: &Doc, decl: Node, name: &str) -> bool {
    annotation_names(doc, decl).iter().any(|n| n == name)
}

fn entity_kind(doc: &Doc, cid: Node) -> Option<String> {
    annotation_names(doc, cid).into_iter().find(|n| ENTITY_ANNOTATIONS.contains(&n.as_str()))
}

fn table_name(doc: &Doc, cid: Node) -> String {
    if let Some(a) = ast::annotation(doc, cid, "Table") {
        if let Some(n) = ast::annotation_attr(doc, a, "name").filter(|n| !n.is_empty()) {
            return n;
        }
    }
    spring_physical_name(doc.ftext(cid, "name"))
}

fn fetch_of(doc: &Doc, a: Node) -> &'static str {
    if let Some(args) = field(a, "arguments") {
        for p in kids(args) {
            if p.kind() == "element_value_pair" && doc.ftext(p, "key") == "fetch" && field(p, "value").is_some_and(|v| doc.text(v).ends_with("EAGER")) {
                return "EAGER";
            }
        }
    }
    "LAZY"
}

/// Коллекция в отдельной таблице: `@ElementCollection` (таблица из `@CollectionTable` или «имя класса сущности_поле»)
/// или связь с явной `@JoinTable`. `@OneToMany` через `mappedBy` или `@JoinColumn` живёт в таблице другой сущности — не берём.
fn collection_field(doc: &Doc, fd: Node, entity_name: &str) -> Option<CollectionField> {
    let rel = ["ElementCollection", "ManyToMany", "OneToMany"].iter().find_map(|n| ast::annotation(doc, fd, n).map(|a| (*n, a)));
    let (rel_name, rel_node) = rel?;
    if ast::has_modifier(fd, "static") {
        return None;
    }
    let field_name = doc.ftext(ast::declarators(fd)[0], "name").to_string();
    let table = if rel_name == "ElementCollection" {
        ast::annotation(doc, fd, "CollectionTable")
            .and_then(|a| ast::annotation_attr(doc, a, "name"))
            .filter(|t| !t.is_empty())
            .unwrap_or_else(|| spring_physical_name(&format!("{entity_name}_{field_name}")))
    } else {
        ast::annotation(doc, fd, "JoinTable").and_then(|a| ast::annotation_attr(doc, a, "name")).filter(|t| !t.is_empty())?
    };
    Some(CollectionField { field: field_name, table, fetch: fetch_of(doc, rel_node) })
}

fn assigns_field(doc: &Doc, body: Node, field_name: &str) -> bool {
    ast::descendants(body).into_iter().filter(|n| n.kind() == "assignment_expression").any(|a| {
        let Some(t) = field(a, "left") else { return false };
        (t.kind() == "identifier" && doc.text(t) == field_name)
            || (t.kind() == "field_access" && field(t, "object").is_some_and(|o| o.kind() == "this") && doc.ftext(t, "field") == field_name)
    })
}

fn describe_entity<'a>(doc: &'a Doc, cid: Node<'a>, fqn: &str, kind: &str) -> Entity {
    let mut e = Entity {
        type_: fqn.to_string(),
        module: doc.module.clone(),
        file: doc.rel.clone(),
        kind: kind.to_string(),
        table: None,
        id_field: None,
        id_generated: false,
        no_arg_ctor: None,
        ctor_statements: 0,
        ctor_assigns_id: false,
        embedded: Vec::new(),
        collections: Vec::new(),
    };
    if kind != "Embeddable" {
        e.table = Some(table_name(doc, cid));
    }
    for fd in ast::field_decls(cid) {
        if has_annotation(doc, fd, "Id") || has_annotation(doc, fd, "EmbeddedId") {
            e.id_field = Some(doc.ftext(ast::declarators(fd)[0], "name").to_string());
            e.id_generated = has_annotation(doc, fd, "GeneratedValue");
        }
    }
    if e.table.is_some() {
        for fd in ast::field_decls(cid) {
            if let Some(cf) = collection_field(doc, fd, doc.ftext(cid, "name")) {
                e.collections.push(cf);
            }
        }
    }
    if let Some(ctor) = no_arg_constructor(cid) {
        let body = field(ctor, "body").unwrap();
        e.no_arg_ctor = Some(format!("method:{}:{}#<init>()", doc.module, fqn));
        e.ctor_statements = statement_count(body);
        e.ctor_assigns_id = e.id_field.as_deref().is_some_and(|f| assigns_field(doc, body, f));
    }
    e
}

fn is_inside_anonymous_class(node: Node, ctor: Node) -> bool {
    let mut cur = node.parent();
    while let Some(c) = cur {
        if c.id() == ctor.id() {
            return false;
        }
        if c.kind() == "object_creation_expression" && kids(c).iter().any(|k| k.kind() == "class_body") {
            return true;
        }
        cur = c.parent();
    }
    false
}

fn is_class_method(cid: Node, doc: &Doc, name: &str) -> bool {
    member_methods(cid).into_iter().any(|m| doc.ftext(m, "name") == name)
}

/// IR тела явного конструктора без аргументов, если в нём есть вызовы.
fn no_arg_constructor_ir(doc: &Doc, cid: Node, fqn: &str, enums: &mut EnumIndex) -> Option<(String, Json)> {
    let ctor = no_arg_constructor(cid)?;
    let body = field(ctor, "body")?;
    let mut calls: Vec<(usize, usize, Json)> = Vec::new();
    for node in ast::descendants(body) {
        if is_inside_anonymous_class(node, ctor) {
            continue;
        }
        if node.kind() == "method_invocation" {
            let name = field(node, "name").unwrap();
            let (l, c) = (line(name), col(name));
            let callee = doc.text(name);
            let scope = field(node, "object");
            let receiver = scope.map(|s| expr_str(doc, s)).unwrap_or_else(|| "this".to_string());
            let enum_const = enums.resolve_call(doc, node);
            let kind = if enum_const.is_some() {
                "ENUM"
            } else if receiver == "this" || (scope.is_none() && is_class_method(cid, doc, callee)) {
                "SAME_CLASS"
            } else {
                "OTHER"
            };
            calls.push((l, c, call_ir(&doc.rel, l, c, callee, &receiver, kind, argument_nodes(node).len(), enum_const.map(|e| (e.type_fqn, e.constant)))));
        } else if node.kind() == "object_creation_expression" {
            let ty = field(node, "type").unwrap();
            let (l, c) = (line(ty), col(node));
            let receiver = ast::type_str(doc, ty);
            calls.push((l, c, call_ir(&doc.rel, l, c, "<init>", &receiver, "CONSTRUCTOR", argument_nodes(node).len(), None)));
        }
    }
    if calls.is_empty() {
        return None;
    }
    calls.sort_by_key(|(l, c, _)| (*l, *c));
    let id = format!("method:{}:{}#<init>()", doc.module, fqn);
    let ir = json!({
        "method_id": id,
        "file": doc.rel,
        "branches": [],
        "calls": calls.into_iter().map(|(_, _, j)| j).collect::<Vec<_>>(),
        "unsupported": [],
    });
    Some((id, ir))
}

#[allow(clippy::too_many_arguments)]
fn call_ir(file: &str, line: usize, col: usize, callee: &str, receiver: &str, kind: &str, arg_count: usize, enum_const: Option<(String, String)>) -> Json {
    let mut o = Obj::new();
    o.insert("call_site_id_guess".into(), Json::Null);
    o.insert("file".into(), file.into());
    o.insert("line".into(), line.into());
    o.insert("col".into(), col.into());
    o.insert("callee".into(), callee.into());
    o.insert("receiver".into(), receiver.into());
    o.insert("kind".into(), kind.into());
    o.insert("arg_count".into(), arg_count.into());
    o.insert("guard".into(), json!([]));
    if let Some((t, c)) = enum_const {
        o.insert("enum_constant".into(), json!({"type": t, "constant": c}));
    }
    Json::Object(o)
}

fn repository_info<'a>(doc: &'a Doc, cid: Node<'a>) -> Option<RepoInfo<'a>> {
    let ext = kids(cid).into_iter().find(|k| k.kind() == "extends_interfaces")?;
    let types: Vec<Node> = kids(ext).into_iter().flat_map(|l| if l.kind() == "type_list" { kids(l) } else { vec![l] }).collect();
    for t in types {
        if !SPRING_DATA_REPOSITORIES.contains(&ast::type_simple_name(doc, t).as_str()) {
            continue;
        }
        let args = ast::type_arguments(t);
        let first = args.first()?;
        let modifying = member_methods(cid).into_iter().filter(|m| has_annotation(doc, *m, "Modifying")).map(|m| doc.ftext(m, "name").to_string()).collect();
        return Some(RepoInfo { module: doc.module.clone(), name: doc.ftext(cid, "name").to_string(), entity_simple: base_name(&ast::type_str(doc, *first)), doc, modifying });
    }
    None
}

fn imported_fqn(doc: &Doc, simple: &str) -> String {
    let suffix = format!(".{simple}");
    if let Some(i) = doc.imports.iter().find(|i| !i.asterisk && !i.is_static && i.name.ends_with(&suffix)) {
        return i.name.clone();
    }
    if doc.pkg.is_empty() { simple.to_string() } else { format!("{}.{simple}", doc.pkg) }
}

/// Сущность репозитория: явный импорт, затем тот же модуль, затем модули, от которых он зависит.
fn resolve_entity<'e>(repo: &RepoInfo, entities: &'e IndexMap<String, EntityDecl>, deps: &[String]) -> Option<&'e EntityDecl<'e>> {
    let suffix = format!(".{}", repo.entity_simple);
    for imp in &repo.doc.imports {
        if !imp.asterisk && !imp.is_static && imp.name.ends_with(&suffix) {
            if let Some(e) = entities.get(&imp.name) {
                return Some(e);
            }
        }
    }
    let same: Vec<&EntityDecl> = entities.values().filter(|e| simple_name(&e.ir.type_) == repo.entity_simple).collect();
    if let Some(e) = same.iter().find(|e| e.ir.module == repo.module) {
        return Some(e);
    }
    for dep in deps {
        if let Some(e) = same.iter().find(|e| &e.ir.module == dep) {
            return Some(e);
        }
    }
    None
}

/// Имя поля-репозитория, на котором сделан вызов: `repo.find(...)` или `this.repo.find(...)`.
fn repository_field_of<'a>(doc: &'a Doc, call: Node) -> Option<&'a str> {
    let scope = field(call, "object")?;
    match scope.kind() {
        "identifier" => Some(doc.text(scope)),
        "field_access" if field(scope, "object").is_some_and(|o| o.kind() == "this") => Some(doc.ftext(scope, "field")),
        _ => None,
    }
}

fn operation_of(callee: &str, modifying: &HashSet<String>) -> &'static str {
    if modifying.contains(callee) {
        "MODIFY"
    } else if callee.starts_with("save") {
        "SAVE"
    } else if callee.starts_with("delete") || callee.starts_with("remove") {
        "DELETE"
    } else if callee.starts_with("exists") {
        "EXISTS"
    } else if callee.starts_with("count") {
        "COUNT"
    } else {
        "READ"
    }
}

type MethodsByName<'a> = HashMap<String, Vec<(&'a Doc, Node<'a>)>>;

/// Объявленные типы параметров и локальных переменных метода (включая переменные цикла).
fn declared_types(doc: &Doc, md: Node) -> HashMap<String, VarType> {
    let mut types = HashMap::new();
    let vt = |t: Node| VarType {
        base: base_name(&ast::type_str(doc, t)),
        optional_of: (ast::type_simple_name(doc, t) == "Optional").then(|| ast::type_arguments(t)).filter(|a| a.len() == 1).map(|a| base_name(&ast::type_str(doc, a[0]))),
    };
    let nodes = ast::descendants(md);
    for p in &nodes {
        match p.kind() {
            "formal_parameter" => {
                if let Some(t) = field(*p, "type") {
                    types.insert(doc.ftext(*p, "name").to_string(), vt(t));
                }
            }
            "spread_parameter" => {
                if let Some(t) = kids(*p).into_iter().find(|k| !matches!(k.kind(), "modifiers" | "variable_declarator")) {
                    types.insert(ast::parameter_name(doc, *p).to_string(), vt(t));
                }
            }
            "catch_formal_parameter" => {
                if let Some(t) = kids(*p).into_iter().find(|k| k.kind() == "catch_type") {
                    types.insert(doc.ftext(*p, "name").to_string(), VarType { base: base_name(&ast::type_str(doc, t)), optional_of: None });
                }
            }
            _ => {}
        }
    }
    for p in &nodes {
        fn decl_type<'t>(doc: &Doc, t: Option<Node<'t>>) -> Option<Node<'t>> {
            t.filter(|t| doc.text(*t) != "var")
        }
        match p.kind() {
            "variable_declarator" => {
                if let Some(t) = decl_type(doc, p.parent().and_then(|d| field(d, "type"))) {
                    types.insert(doc.ftext(*p, "name").to_string(), vt(t));
                }
            }
            "enhanced_for_statement" | "resource" => {
                if let (Some(t), Some(_)) = (decl_type(doc, field(*p, "type")), field(*p, "name")) {
                    types.insert(doc.ftext(*p, "name").to_string(), vt(t));
                }
            }
            _ => {}
        }
    }
    types
}

/// Выражение — экземпляр сущности: переменная её типа или `get/orElse*` у переменной `Optional<сущность>`.
fn is_entity_value(doc: &Doc, e: Node, types: &HashMap<String, VarType>, entity_simple: &str) -> bool {
    if e.kind() == "identifier" {
        return types.get(doc.text(e)).is_some_and(|t| t.base == entity_simple);
    }
    if e.kind() == "method_invocation" && matches!(doc.ftext(e, "name"), "get" | "orElse" | "orElseThrow" | "orElseGet") {
        if let Some(s) = field(e, "object").filter(|s| s.kind() == "identifier") {
            return types.get(doc.text(s)).and_then(|t| t.optional_of.as_deref()) == Some(entity_simple);
        }
    }
    false
}

/// Обращения к ленивым коллекциям сущности в теле метода, кроме геттера внутри `return`.
fn collection_uses(doc: &Doc, md: Node, entity_simple: &str, lazy: &IndexMap<String, String>, loaded: &mut Vec<String>, reasons: &mut Vec<String>) {
    let types = declared_types(doc, md);
    for c in ast::descendants(md).into_iter().filter(|n| n.kind() == "method_invocation") {
        let Some(f) = lazy.get(doc.ftext(c, "name")) else { continue };
        let Some(scope) = field(c, "object") else { continue };
        if ast::ancestor(c, |k| k == "return_statement").is_some() || !is_entity_value(doc, scope, &types, entity_simple) {
            continue;
        }
        if !loaded.contains(f) {
            loaded.push(f.clone());
        }
        reasons.push(format!("{} line {}: {}", doc.ftext(md, "name"), line(c), expr_str(doc, c)));
    }
}

/// Какие ленивые коллекции сущности метод с вызовом репозитория загружает, пока он на стеке.
/// Геттер внутри `return` не считается: такую коллекцию загрузит сериализация ответа. На один уровень смотрим
/// в проектные методы того же модуля, которым передана сущность.
fn loaded_collections(doc: &Doc, call: Node, entity: &EntityDecl, methods: &MethodsByName, rc: &mut RepoCall) {
    let mut lazy: IndexMap<String, String> = IndexMap::new();
    for cf in entity.ir.collections.iter().filter(|c| c.fetch == "LAZY") {
        let mut ch = cf.field.chars();
        let first = ch.next().unwrap().to_uppercase().collect::<String>();
        lazy.insert(format!("get{first}{}", ch.as_str()), cf.field.clone());
    }
    let Some(md) = ast::ancestor(call, |k| k == "method_declaration") else { return };
    if lazy.is_empty() {
        return;
    }
    let entity_simple = simple_name(&entity.ir.type_).to_string();
    let mut loaded = Vec::new();
    let mut reasons = Vec::new();
    collection_uses(doc, md, &entity_simple, &lazy, &mut loaded, &mut reasons);
    let types = declared_types(doc, md);
    for c in ast::descendants(md).into_iter().filter(|n| n.kind() == "method_invocation") {
        let args = argument_nodes(c);
        for (i, a) in args.iter().enumerate() {
            if !is_entity_value(doc, *a, &types, &entity_simple) {
                continue;
            }
            for (cdoc, callee) in methods.get(doc.ftext(c, "name")).map(Vec::as_slice).unwrap_or(&[]) {
                let params = ast::parameter_nodes(*callee);
                if callee.id() != md.id() && params.len() == args.len() && base_name(&ast::parameter_type(cdoc, params[i])) == entity_simple {
                    collection_uses(cdoc, *callee, &entity_simple, &lazy, &mut loaded, &mut reasons);
                }
            }
        }
    }
    rc.collections_loaded = Some(loaded);
    rc.collections_loaded_reason = Some(reasons);
}

/// Локальная переменная, в которую сохранён результат вызова: `List<X> xs = repo.find(...)` или `xs = repo.find(...)`.
fn result_variable(doc: &Doc, call: Node) -> Option<String> {
    let p = call.parent()?;
    match p.kind() {
        "variable_declarator" => Some(doc.ftext(p, "name").to_string()),
        "assignment_expression" => field(p, "left").filter(|l| l.kind() == "identifier").map(|l| doc.text(l).to_string()),
        _ => None,
    }
}

/// Вызовы библиотеки коллекций на результате чтения, которые сравнивают элементы через `equals`:
/// `list.contains(x)` вызывает `x.equals(элемент)`. Берём, только если аргумент того же типа, что сущность,
/// и у сущности рукописный `equals(Object)`.
fn element_callbacks(doc: &Doc, call: Node, entity: &EntityDecl, rc: &mut RepoCall) {
    let own_equals = member_methods(entity.cid).into_iter().any(|m| entity.doc.ftext(m, "name") == "equals" && ast::parameter_nodes(m).len() == 1 && field(m, "body").is_some());
    let md = ast::ancestor(call, |k| k == "method_declaration");
    let var = result_variable(doc, call);
    let (Some(md), Some(var), true) = (md, var, own_equals) else { return };
    let entity_simple = simple_name(&entity.ir.type_).to_string();
    let types = declared_types(doc, md);
    let mut out = Vec::new();
    for c in ast::descendants(md).into_iter().filter(|n| n.kind() == "method_invocation") {
        let name = doc.ftext(c, "name");
        let args = argument_nodes(c);
        let Some(scope) = field(c, "object") else { continue };
        if !EQUALITY_LOOKUPS.contains(&name) || args.len() != 1 || scope.kind() != "identifier" || doc.text(scope) != var || !is_entity_value(doc, args[0], &types, &entity_simple) || !before(call, c) {
            continue;
        }
        let n = field(c, "name").unwrap();
        out.push((format!("method:{}:{}#equals(java.lang.Object)", entity.ir.module, entity.ir.type_), name.to_string(), line(n), col(n)));
    }
    if !out.is_empty() {
        rc.element_callbacks = Some(out);
    }
}

fn mark(rc: &mut RepoCall, value: bool, reason: String) {
    rc.id_assigned = Some(value);
    rc.id_assigned_reason = Some(reason);
}

/// Инициализатор локальной переменной (объявление или последнее присваивание до вызова).
fn initializer_of<'a>(doc: &Doc, at: Node<'a>, var: &str) -> Option<Node<'a>> {
    let body = enclosing_body(at);
    let nodes = ast::descendants(body);
    let mut result: Option<Node> = None;
    for vd in nodes.iter().filter(|n| n.kind() == "variable_declarator") {
        if doc.ftext(*vd, "name") == var && before(*vd, at) {
            if let Some(v) = field(*vd, "value") {
                result = Some(v);
            }
        }
    }
    for a in nodes.iter().filter(|n| n.kind() == "assignment_expression") {
        if field(*a, "left").is_some_and(|l| l.kind() == "identifier" && doc.text(l) == var) && before(*a, at) && result.is_none_or(|r| before(r, *a)) {
            result = field(*a, "right");
        }
    }
    result
}

fn is_null(n: Node) -> bool {
    n.kind() == "null_literal"
}

/// Аргумент конструктора с параметрами, который попадает в поле id (явный конструктор или `@AllArgsConstructor`).
fn id_from_constructor_args(entity: &EntityDecl, oce: Node) -> Option<bool> {
    let id_field = entity.ir.id_field.as_deref()?;
    let edoc = entity.doc;
    let args = argument_nodes(oce);
    let n = args.len();
    for cd in constructors(entity.cid) {
        let params = ast::parameter_nodes(cd);
        if params.len() != n {
            continue;
        }
        for a in ast::descendants(field(cd, "body").unwrap()).into_iter().filter(|x| x.kind() == "assignment_expression") {
            let t = field(a, "left").unwrap();
            let to_id = (t.kind() == "field_access" && edoc.ftext(t, "field") == id_field) || (t.kind() == "identifier" && edoc.text(t) == id_field);
            if to_id {
                if let Some(v) = field(a, "right").filter(|v| v.kind() == "identifier") {
                    for (i, p) in params.iter().enumerate() {
                        if ast::parameter_name(edoc, *p) == edoc.text(v) {
                            return Some(!is_null(args[i]));
                        }
                    }
                }
                return None; // id присваивается не параметром: значение неизвестно
            }
        }
        return Some(false); // конструктор id не трогает: он остаётся null, Spring Data делает persist
    }
    if has_annotation(edoc, entity.cid, "AllArgsConstructor") {
        let mut names = Vec::new();
        for fd in ast::field_decls(entity.cid) {
            if !ast::has_modifier(fd, "static") {
                names.extend(ast::declarators(fd).into_iter().map(|v| edoc.ftext(v, "name").to_string()));
            }
        }
        let idx = names.iter().position(|f| f == id_field);
        if let (Some(idx), true) = (idx, names.len() == n) {
            return Some(!is_null(args[idx]));
        }
    }
    None
}

/// Задан ли id сущности до `save`. Spring Data вызывает `persist` для сущности с `id == null` и `merge` для остальных;
/// `merge` загружает строку и создаёт экземпляр конструктором без аргументов.
fn id_assigned(doc: &Doc, save: Node, entity: &EntityDecl, rc: &mut RepoCall) {
    let Some(id_field) = entity.ir.id_field.clone() else { return };
    let args = argument_nodes(save);
    if args.len() != 1 {
        return;
    }
    let arg = args[0];
    let mut init = Some(arg);
    let mut var: Option<String> = None;
    if arg.kind() == "identifier" {
        let v = doc.text(arg).to_string();
        init = initializer_of(doc, save, &v);
        var = Some(v);
    }
    let mut ch = id_field.chars();
    let setter = format!("set{}{}", ch.next().unwrap().to_uppercase(), ch.as_str());
    if let Some(v) = &var {
        for c in ast::descendants(enclosing_body(save)).into_iter().filter(|n| n.kind() == "method_invocation") {
            if doc.ftext(c, "name") == setter && before(c, save) && field(c, "object").is_some_and(|s| expr_str(doc, s) == *v) {
                mark(rc, true, format!("line {}: {}", line(c), expr_str(doc, c)));
                return;
            }
        }
    }
    let Some(init) = init else { return };
    if init.kind() == "object_creation_expression" && field(init, "type").is_some_and(|t| simple_name(&entity.ir.type_) == base_name(&ast::type_str(doc, t))) {
        if argument_nodes(init).is_empty() {
            let a = entity.ir.ctor_assigns_id;
            mark(rc, a, if a { format!("no-arg ctor assigns {id_field}") } else { format!("no-arg ctor leaves {id_field} null") });
            return;
        }
        if let Some(by_args) = id_from_constructor_args(entity, init) {
            mark(rc, by_args, format!("line {}: {}", line(init), expr_str(doc, init)));
        }
        return;
    }
    if init.kind() == "method_invocation" && doc.ftext(init, "name") == "build" {
        let sets_id = ast::descendants(init).into_iter().any(|c| c.kind() == "method_invocation" && doc.ftext(c, "name") == id_field);
        mark(rc, sets_id, format!("builder {} {}", if sets_id { "sets" } else { "omits" }, id_field));
    }
}

fn describe_call<'a>(doc: &Doc, call: Node<'a>, repo: &RepoInfo, entity: Option<&EntityDecl>) -> RepoCall {
    let name = field(call, "name").unwrap();
    let callee = doc.text(name).to_string();
    let operation = operation_of(&callee, &repo.modifying);
    let mut rc = RepoCall {
        file: doc.rel.clone(),
        line: line(name),
        col: col(name),
        callee,
        repository: repo.name.clone(),
        entity: entity.map(|e| e.ir.type_.clone()),
        operation,
        expects: None,
        expects_reason: None,
        id_assigned: None,
        id_assigned_reason: None,
        collections_loaded: None,
        collections_loaded_reason: None,
        element_callbacks: None,
    };
    if operation == "READ" {
        let (e, r) = expect::analyze(doc, call);
        rc.expects = Some(e);
        rc.expects_reason = Some(r);
    }
    if operation == "SAVE" {
        if let Some(e) = entity {
            id_assigned(doc, call, e, &mut rc);
        }
    }
    rc
}

fn entity_json(e: &Entity) -> Json {
    let mut o = Obj::new();
    o.insert("type".into(), e.type_.clone().into());
    o.insert("module".into(), e.module.clone().into());
    o.insert("file".into(), e.file.clone().into());
    o.insert("kind".into(), e.kind.clone().into());
    if let Some(t) = &e.table {
        o.insert("table".into(), t.clone().into());
    }
    if let Some(t) = &e.id_field {
        o.insert("id_field".into(), t.clone().into());
    }
    o.insert("id_generated".into(), e.id_generated.into());
    if let Some(t) = &e.no_arg_ctor {
        o.insert("no_arg_ctor".into(), t.clone().into());
    }
    o.insert("ctor_statements".into(), e.ctor_statements.into());
    o.insert("ctor_assigns_id".into(), e.ctor_assigns_id.into());
    o.insert("embedded".into(), Json::Array(e.embedded.iter().map(|s| s.clone().into()).collect()));
    o.insert("collections".into(), Json::Array(e.collections.iter().map(|c| json!({"field": c.field, "table": c.table, "fetch": c.fetch})).collect()));
    Json::Object(o)
}

fn call_json(c: &RepoCall) -> Json {
    let mut o = Obj::new();
    o.insert("file".into(), c.file.clone().into());
    o.insert("line".into(), c.line.into());
    o.insert("col".into(), c.col.into());
    o.insert("callee".into(), c.callee.clone().into());
    o.insert("repository".into(), c.repository.clone().into());
    if let Some(e) = &c.entity {
        o.insert("entity".into(), e.clone().into());
    }
    o.insert("operation".into(), c.operation.into());
    if let Some(e) = c.expects {
        o.insert("expects".into(), e.into());
    }
    if let Some(e) = &c.expects_reason {
        o.insert("expects_reason".into(), e.clone().into());
    }
    if let Some(e) = c.id_assigned {
        o.insert("id_assigned".into(), e.into());
    }
    if let Some(e) = &c.id_assigned_reason {
        o.insert("id_assigned_reason".into(), e.clone().into());
    }
    if let Some(l) = &c.collections_loaded {
        o.insert("collections_loaded".into(), Json::Array(l.iter().map(|s| s.clone().into()).collect()));
    }
    if let Some(l) = &c.collections_loaded_reason {
        o.insert("collections_loaded_reason".into(), Json::Array(l.iter().map(|s| s.clone().into()).collect()));
    }
    if let Some(l) = &c.element_callbacks {
        o.insert("element_callbacks".into(), Json::Array(l.iter().map(|(m, v, ln, cl)| json!({"method": m, "via": v, "line": ln, "col": cl})).collect()));
    }
    Json::Object(o)
}

/// `enum_docs` — все `.java` проекта со словом `enum ` (общий обход `scanEnums`), `docs` — `src/main/java`.
pub fn scan(sk: &Skeleton, docs: &[Doc], enum_docs: &[Doc]) -> Report {
    let mut enums = EnumIndex::new(sk.shared_modules());
    for d in enum_docs {
        enums.scan_doc(d);
    }
    for d in docs {
        enums.index_doc(d);
    }

    let mut entities: IndexMap<String, EntityDecl> = IndexMap::new();
    let mut repos: HashMap<String, RepoInfo> = HashMap::new();
    let mut no_arg: BTreeMap<String, usize> = BTreeMap::new();
    let mut ctors: Vec<(String, Json)> = Vec::new();

    // Проход 1: сущности, репозитории, конструкторы без аргументов
    for doc in docs {
        for cid in ast::descendants(doc.root()).into_iter().filter(|n| is_class(n.kind())) {
            let fqn = entity_binary_name(doc, cid);
            if cid.kind() == "interface_declaration" {
                if let Some(r) = repository_info(doc, cid) {
                    repos.insert(format!("{}:{}", doc.module, doc.ftext(cid, "name")), r);
                }
                continue;
            }
            if let Some(kind) = entity_kind(doc, cid) {
                let ir = describe_entity(doc, cid, &fqn, &kind);
                entities.insert(fqn.clone(), EntityDecl { ir, cid, doc });
            }
            if let Some(ctor) = no_arg_constructor(cid) {
                no_arg.insert(format!("method:{}:{}#<init>()", doc.module, fqn), statement_count(field(ctor, "body").unwrap()));
            }
            if let Some(c) = no_arg_constructor_ir(doc, cid, &fqn, &mut enums) {
                ctors.push(c);
            }
        }
    }

    // Встраиваемые поля сущностей: тип резолвим по известным встраиваемым классам
    let mut embeddable_by_simple: HashMap<String, String> = HashMap::new();
    for e in entities.values().filter(|e| e.ir.kind == "Embeddable") {
        embeddable_by_simple.insert(simple_name(&e.ir.type_).to_string(), e.ir.type_.clone());
    }
    for e in entities.values_mut() {
        for fd in ast::field_decls(e.cid) {
            let et = element_type_text(e.doc, fd);
            if ast::has_modifier(fd, "static") || COLLECTION_TYPES.contains(&base_name(&et).as_str()) {
                continue;
            }
            let simple = base_name(&et);
            let embedded_ann = has_annotation(e.doc, fd, "Embedded") || has_annotation(e.doc, fd, "EmbeddedId");
            if embedded_ann || embeddable_by_simple.contains_key(&simple) {
                let target = embeddable_by_simple.get(&simple).cloned().unwrap_or_else(|| imported_fqn(e.doc, &simple));
                if !e.ir.embedded.contains(&target) {
                    e.ir.embedded.push(target);
                }
            }
        }
    }

    // Методы классов по модулю и имени: для захода в проектный метод, которому передана сущность
    let mut methods_by_module: HashMap<&str, MethodsByName> = HashMap::new();
    for doc in docs {
        for md in ast::descendants(doc.root()).into_iter().filter(|n| n.kind() == "method_declaration" && field(*n, "body").is_some()) {
            methods_by_module.entry(doc.module.as_str()).or_default().entry(doc.ftext(md, "name").to_string()).or_default().push((doc, md));
        }
    }
    let empty = MethodsByName::new();

    // Проход 2: вызовы репозиториев во всех классах проекта
    let mut calls: Vec<RepoCall> = Vec::new();
    for doc in docs {
        for cid in ast::descendants(doc.root()).into_iter().filter(|n| n.kind() == "class_declaration") {
            let mut repo_fields: HashMap<String, &RepoInfo> = HashMap::new();
            for fd in ast::field_decls(cid) {
                if let Some(repo) = repos.get(&format!("{}:{}", doc.module, base_name(&element_type_text(doc, fd)))) {
                    for vd in ast::declarators(fd) {
                        repo_fields.insert(doc.ftext(vd, "name").to_string(), repo);
                    }
                }
            }
            if repo_fields.is_empty() {
                continue;
            }
            for call in ast::descendants(cid).into_iter().filter(|n| n.kind() == "method_invocation") {
                if ast::ancestor(call, is_class).is_none_or(|a| a.id() != cid.id()) {
                    continue; // вызов во вложенном классе разберётся при его обходе
                }
                let Some(repo) = repository_field_of(doc, call).and_then(|f| repo_fields.get(f)) else { continue };
                let entity = resolve_entity(repo, &entities, &sk.dependencies(&repo.module));
                let mut rc = describe_call(doc, call, repo, entity);
                if rc.operation == "READ" {
                    if let Some(e) = entity {
                        loaded_collections(doc, call, e, methods_by_module.get(doc.module.as_str()).unwrap_or(&empty), &mut rc);
                        element_callbacks(doc, call, e, &mut rc);
                    }
                }
                calls.push(rc);
            }
        }
    }

    let mut ent: Vec<&EntityDecl> = entities.values().collect();
    ent.sort_by(|a, b| a.ir.type_.cmp(&b.ir.type_));
    ctors.sort_by(|a, b| a.0.cmp(&b.0));
    calls.sort_by(|a, b| (&a.file, a.line, a.col).cmp(&(&b.file, b.line, b.col)));

    let mut root = Obj::new();
    root.insert("schema".into(), "entity_ir/2".into());
    root.insert("entities".into(), Json::Array(ent.iter().map(|e| entity_json(&e.ir)).collect()));
    root.insert("repository_calls".into(), Json::Array(calls.iter().map(call_json).collect()));
    root.insert("no_arg_ctor_statements".into(), Json::Object(no_arg.into_iter().map(|(k, v)| (k, v.into())).collect()));
    root.insert("constructors".into(), Json::Array(ctors.iter().map(|(_, j)| j.clone()).collect()));
    Report { entities: ent.len(), repository_calls: calls.len(), constructors: ctors.len(), json: Json::Object(root) }
}

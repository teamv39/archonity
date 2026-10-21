//! IR тела одного метода по контракту `archparse/README.md`, раздел 3.6: дерево операторов и выражений,
//! вызовы привязаны к call_site скелета, константы enum и `static final` вычислены (порт `BodyIrBuilder`).

use std::collections::HashSet;

use serde_json::{json, Map, Value as Json};
use tree_sitter::Node;

use crate::ast::{self, argument_nodes, col, expr_str, field, fields, kids, line, type_name_with_scope, type_str, Doc};
use crate::index::ProjectIndex;
use crate::lit::literal;
use crate::skeleton::{MethodNode, Skeleton};

type Obj = Map<String, Json>;

pub struct BodyBuilder<'a> {
    sk: &'a Skeleton,
    project: &'a ProjectIndex<'a>,
    doc: &'a Doc,
    method: &'a MethodNode,
    params: HashSet<String>,
    locals: Vec<HashSet<String>>,
    fields: HashSet<String>,
    /// FQN объемлющих типов, изнутри наружу.
    enclosing: Vec<String>,
    /// call_site, которые встретились в теле (для проверки покрытия).
    pub call_sites_seen: Vec<String>,
    pub ir_calls: usize,
}

fn op(kind: &str, n: Node) -> Obj {
    let mut o = Obj::new();
    o.insert("op".into(), kind.into());
    o.insert("line".into(), line(n).into());
    o
}

fn name_ref(name: &str, r: &str) -> Json {
    json!({"name": name, "ref": r})
}

impl<'a> BodyBuilder<'a> {
    pub fn new(sk: &'a Skeleton, project: &'a ProjectIndex<'a>, doc: &'a Doc, method: &'a MethodNode, decl: Node<'a>) -> Self {
        let mut b = BodyBuilder {
            sk,
            project,
            doc,
            method,
            params: HashSet::new(),
            locals: Vec::new(),
            fields: HashSet::new(),
            enclosing: Vec::new(),
            call_sites_seen: Vec::new(),
            ir_calls: 0,
        };
        for p in ast::parameter_nodes(decl) {
            b.params.insert(ast::parameter_name(doc, p).to_string());
        }
        let mut cur = decl.parent();
        while let Some(c) = cur {
            if ast::is_type_decl(c.kind()) {
                for fd in ast::field_decls(c) {
                    for v in ast::declarators(fd) {
                        b.fields.insert(doc.ftext(v, "name").to_string());
                    }
                }
                if c.kind() == "enum_declaration" {
                    if let Some(body) = field(c, "body") {
                        for e in kids(body).into_iter().filter(|e| e.kind() == "enum_constant") {
                            b.fields.insert(doc.ftext(e, "name").to_string());
                        }
                    }
                }
                b.enclosing.push(ast::binary_name(doc, c));
            } else if c.kind() == "object_creation_expression" {
                if let Some(body) = kids(c).into_iter().find(|k| k.kind() == "class_body") {
                    for m in kids(body).into_iter().filter(|m| m.kind() == "field_declaration") {
                        for v in ast::declarators(m) {
                            b.fields.insert(doc.ftext(v, "name").to_string());
                        }
                    }
                }
            }
            cur = c.parent();
        }
        b
    }

    pub fn build(&mut self, decl: Node<'a>, body: Node<'a>) -> Json {
        let mut out = Obj::new();
        out.insert("file".into(), self.doc.rel.clone().into());
        out.insert("line".into(), self.method.line.into());
        out.insert("end".into(), self.method.end.into());
        let ps: Vec<Json> = ast::parameter_nodes(decl)
            .into_iter()
            .map(|p| json!({"name": ast::parameter_name(self.doc, p), "type": ast::parameter_type(self.doc, p)}))
            .collect();
        out.insert("params".into(), Json::Array(ps));
        let b = self.block(body);
        out.insert("body".into(), b);
        Json::Object(out)
    }

    // ------------------------------------------------------------------
    // Операторы
    // ------------------------------------------------------------------

    /// Операторы блока (`BlockStmt.getStatements()`): пустой оператор `;` в IR не попадает.
    fn block(&mut self, s: Node<'a>) -> Json {
        let mut out = Vec::new();
        self.locals.push(HashSet::new());
        if matches!(s.kind(), "block" | "constructor_body") {
            for st in kids(s) {
                self.stmt(st, &mut out);
            }
        } else {
            self.stmt(s, &mut out);
        }
        self.locals.pop();
        Json::Array(out)
    }

    fn stmt(&mut self, s: Node<'a>, out: &mut Vec<Json>) {
        match s.kind() {
            "expression_statement" => {
                let Some(e) = kids(s).into_iter().next() else { return };
                if e.kind() == "assignment_expression" {
                    let mut o = op("assign", s);
                    o.insert("target".into(), self.expr(field(e, "left").unwrap()));
                    o.insert("operator".into(), self.doc.ftext(e, "operator").into());
                    o.insert("expr".into(), self.expr(field(e, "right").unwrap()));
                    out.push(Json::Object(o));
                } else {
                    let mut o = op("expr", s);
                    o.insert("expr".into(), self.expr(e));
                    out.push(Json::Object(o));
                }
            }
            "local_variable_declaration" => self.declarations(s, out),
            "if_statement" => {
                let mut o = op("if", s);
                o.insert("id".into(), format!("b{}", line(s)).into());
                o.insert("cond".into(), self.expr(ast::stmt_condition(s).unwrap()));
                o.insert("then".into(), self.block(field(s, "consequence").unwrap()));
                let els = match field(s, "alternative") {
                    Some(a) => self.block(a),
                    None => Json::Array(vec![]),
                };
                o.insert("else".into(), els);
                out.push(Json::Object(o));
            }
            "switch_expression" => out.push(self.switch(s)),
            "while_statement" => {
                let mut o = op("while", s);
                o.insert("cond".into(), self.expr(ast::stmt_condition(s).unwrap()));
                o.insert("body".into(), self.block(field(s, "body").unwrap()));
                out.push(Json::Object(o));
            }
            "do_statement" => {
                let mut o = op("do", s);
                o.insert("body".into(), self.block(field(s, "body").unwrap()));
                o.insert("cond".into(), self.expr(ast::stmt_condition(s).unwrap()));
                out.push(Json::Object(o));
            }
            "for_statement" => out.push(self.for_stmt(s)),
            "enhanced_for_statement" => {
                let mut o = op("foreach", s);
                let iter = field(s, "value").unwrap();
                o.insert("id".into(), format!("f{}:{}", line(s), expr_str(self.doc, iter)).into());
                let var = self.doc.ftext(s, "name").to_string();
                o.insert("var".into(), var.clone().into());
                let dims = field(s, "dimensions").map(|d| self.doc.text(d).matches('[').count()).unwrap_or(0);
                o.insert("var_type".into(), format!("{}{}", field(s, "type").map(|t| type_str(self.doc, t)).unwrap_or_default(), "[]".repeat(dims)).into());
                o.insert("iter".into(), self.expr(iter));
                self.locals.push(HashSet::from([var]));
                o.insert("body".into(), self.block(field(s, "body").unwrap()));
                self.locals.pop();
                out.push(Json::Object(o));
            }
            "try_statement" | "try_with_resources_statement" => out.push(self.try_stmt(s)),
            "return_statement" => {
                let mut o = op("return", s);
                if let Some(e) = kids(s).into_iter().next() {
                    o.insert("expr".into(), self.expr(e));
                }
                out.push(Json::Object(o));
            }
            "throw_statement" => {
                let mut o = op("throw", s);
                o.insert("expr".into(), self.expr(kids(s)[0]));
                out.push(Json::Object(o));
            }
            "break_statement" | "continue_statement" => {
                let mut o = op(if s.kind() == "break_statement" { "break" } else { "continue" }, s);
                if let Some(l) = kids(s).into_iter().next() {
                    o.insert("label".into(), self.doc.text(l).into());
                }
                out.push(Json::Object(o));
            }
            "block" => {
                let mut o = op("block", s);
                o.insert("body".into(), self.block(s));
                out.push(Json::Object(o));
            }
            "synchronized_statement" => {
                let mut o = op("block", s);
                let lock = kids(s).into_iter().find(|k| k.kind() == "parenthesized_expression").and_then(ast::cond_inner).unwrap();
                o.insert("lock".into(), self.expr(lock));
                o.insert("body".into(), self.block(field(s, "body").unwrap()));
                out.push(Json::Object(o));
            }
            "labeled_statement" => {
                let ks = kids(s);
                let mut o = op("block", s);
                o.insert("label".into(), self.doc.text(ks[0]).into());
                o.insert("body".into(), self.block(ks[1]));
                out.push(Json::Object(o));
            }
            "explicit_constructor_invocation" => {
                let mut call = Obj::new();
                self.put_call_id(&mut call, line(s), col(s), None);
                let this = field(s, "constructor").is_some_and(|c| c.kind() == "this");
                call.insert("callee".into(), (if this { "this" } else { "super" }).into());
                call.insert("recv".into(), Json::Null);
                let args: Vec<Json> = argument_nodes(s).into_iter().map(|a| self.expr(a)).collect();
                call.insert("args".into(), Json::Array(args));
                let mut o = op("expr", s);
                o.insert("expr".into(), Json::Object(call));
                out.push(Json::Object(o));
            }
            ";" => {}
            _ => {
                let mut o = op("unsupported", s);
                o.insert("text".into(), self.doc.text(s).lines().next().unwrap_or("").into());
                out.push(Json::Object(o));
            }
        }
    }

    fn declarations(&mut self, decl: Node<'a>, out: &mut Vec<Json>) {
        for vd in ast::declarators(decl) {
            let name = self.doc.ftext(vd, "name").to_string();
            let mut o = op("assign", vd);
            o.insert("target".into(), name_ref(&name, "local"));
            o.insert("decl".into(), ast::declarator_type(self.doc, decl, vd).into());
            o.insert("operator".into(), "=".into());
            if let Some(init) = field(vd, "value") {
                o.insert("expr".into(), self.expr(init));
            }
            self.declare(&name);
            out.push(Json::Object(o));
        }
    }

    fn declare(&mut self, name: &str) {
        if self.locals.is_empty() {
            self.locals.push(HashSet::new());
        }
        self.locals.last_mut().unwrap().insert(name.to_string());
    }

    fn is_local(&self, name: &str) -> bool {
        self.locals.iter().any(|s| s.contains(name))
    }

    fn for_stmt(&mut self, s: Node<'a>) -> Json {
        let mut o = op("for", s);
        self.locals.push(HashSet::new());
        let mut init = Vec::new();
        for e in fields(s, "init") {
            if e.kind() == "local_variable_declaration" {
                self.declarations(e, &mut init);
            } else {
                let mut x = op("expr", e);
                x.insert("expr".into(), self.expr(e));
                init.push(Json::Object(x));
            }
        }
        o.insert("init".into(), Json::Array(init));
        let cond = match field(s, "condition") {
            Some(c) => self.expr(c),
            None => Json::Null,
        };
        o.insert("cond".into(), cond);
        let upd: Vec<Json> = fields(s, "update").into_iter().map(|e| self.expr(e)).collect();
        o.insert("update".into(), Json::Array(upd));
        o.insert("body".into(), self.block(field(s, "body").unwrap()));
        self.locals.pop();
        Json::Object(o)
    }

    fn try_stmt(&mut self, s: Node<'a>) -> Json {
        let mut o = op("try", s);
        o.insert("id".into(), format!("t{}", line(s)).into());
        self.locals.push(HashSet::new());
        let mut res = Vec::new();
        if let Some(spec) = field(s, "resources") {
            for r in kids(spec).into_iter().filter(|k| k.kind() == "resource") {
                if let Some(name) = field(r, "name") {
                    let nm = self.doc.text(name).to_string();
                    let mut a = op("assign", name);
                    a.insert("target".into(), name_ref(&nm, "local"));
                    a.insert("decl".into(), field(r, "type").map(|t| type_str(self.doc, t)).unwrap_or_default().into());
                    a.insert("operator".into(), "=".into());
                    if let Some(v) = field(r, "value") {
                        a.insert("expr".into(), self.expr(v));
                    }
                    self.declare(&nm);
                    res.push(Json::Object(a));
                } else if let Some(e) = kids(r).into_iter().next() {
                    let mut x = op("expr", e);
                    x.insert("expr".into(), self.expr(e));
                    res.push(Json::Object(x));
                }
            }
        }
        o.insert("resources".into(), Json::Array(res));
        o.insert("body".into(), self.block(field(s, "body").unwrap()));
        self.locals.pop();
        let mut catches = Vec::new();
        let mut finally = Json::Null;
        for c in kids(s) {
            match c.kind() {
                "catch_clause" => {
                    let mut x = Obj::new();
                    let param = kids(c).into_iter().find(|k| k.kind() == "catch_formal_parameter").unwrap();
                    let types: Vec<Json> = kids(param)
                        .into_iter()
                        .filter(|k| k.kind() == "catch_type")
                        .flat_map(kids)
                        .map(|t| Json::String(type_str(self.doc, t)))
                        .collect();
                    x.insert("types".into(), Json::Array(types));
                    let var = self.doc.ftext(param, "name").to_string();
                    x.insert("var".into(), var.clone().into());
                    self.locals.push(HashSet::from([var]));
                    x.insert("body".into(), self.block(field(c, "body").unwrap()));
                    self.locals.pop();
                    catches.push(Json::Object(x));
                }
                "finally_clause" => {
                    let b = kids(c).into_iter().find(|k| k.kind() == "block").unwrap();
                    finally = self.block(b);
                }
                _ => {}
            }
        }
        o.insert("catches".into(), Json::Array(catches));
        o.insert("finally".into(), finally);
        Json::Object(o)
    }

    fn switch(&mut self, s: Node<'a>) -> Json {
        let mut o = op("switch", s);
        o.insert("selector".into(), self.expr(ast::stmt_condition(s).unwrap()));
        let mut cases = Vec::new();
        self.locals.push(HashSet::new());
        let body = field(s, "body").unwrap();
        for entry in kids(body) {
            match entry.kind() {
                "switch_block_statement_group" => {
                    let ks = kids(entry);
                    let labels: Vec<Node> = ks.iter().copied().filter(|k| k.kind() == "switch_label").collect();
                    let stmts: Vec<Node> = ks.iter().copied().filter(|k| k.kind() != "switch_label").collect();
                    for (i, l) in labels.iter().enumerate() {
                        let mut c = Obj::new();
                        let ls: Vec<Json> = kids(*l).into_iter().map(|e| self.case_label(e)).collect();
                        c.insert("labels".into(), Json::Array(ls));
                        let mut b = Vec::new();
                        if i + 1 == labels.len() {
                            for st in &stmts {
                                self.stmt(*st, &mut b);
                            }
                        }
                        c.insert("body".into(), Json::Array(b));
                        cases.push(Json::Object(c));
                    }
                }
                "switch_rule" => {
                    let ks = kids(entry);
                    let mut c = Obj::new();
                    let label = ks.iter().find(|k| k.kind() == "switch_label");
                    let ls: Vec<Json> = label.map(|l| kids(*l)).unwrap_or_default().into_iter().map(|e| self.case_label(e)).collect();
                    c.insert("labels".into(), Json::Array(ls));
                    let mut b = Vec::new();
                    for st in ks.iter().filter(|k| k.kind() != "switch_label") {
                        self.stmt(*st, &mut b);
                    }
                    c.insert("body".into(), Json::Array(b));
                    cases.push(Json::Object(c));
                }
                _ => {}
            }
        }
        self.locals.pop();
        o.insert("cases".into(), Json::Array(cases));
        Json::Object(o)
    }

    fn case_label(&mut self, l: Node<'a>) -> Json {
        if l.kind() == "identifier" {
            let n = self.doc.text(l);
            if !self.is_local(n) && !self.params.contains(n) {
                if let Some(e) = self.project.unique_enum_of(n) {
                    return self.enum_node(&e.to_string(), n);
                }
            }
        }
        self.expr(l)
    }

    // ------------------------------------------------------------------
    // Выражения
    // ------------------------------------------------------------------

    pub fn expr(&mut self, e: Node<'a>) -> Json {
        let doc = self.doc;
        if ast::is_comment(e) {
            return Json::Null;
        }
        match e.kind() {
            "parenthesized_expression" => match kids(e).into_iter().next() {
                Some(i) => self.expr(i),
                None => Json::Null,
            },
            _ if crate::lit::is_literal_node(e) => literal(doc, e),
            "identifier" => self.name(e),
            "field_access" => self.field_access(e),
            "method_invocation" => self.method_call(e),
            "object_creation_expression" => self.object_creation(e),
            "binary_expression" => {
                let mut o = Obj::new();
                o.insert("bin".into(), doc.ftext(e, "operator").into());
                o.insert("l".into(), self.expr(field(e, "left").unwrap()));
                o.insert("r".into(), self.expr(field(e, "right").unwrap()));
                Json::Object(o)
            }
            "unary_expression" => {
                let mut o = Obj::new();
                o.insert("un".into(), doc.ftext(e, "operator").into());
                o.insert("e".into(), self.expr(field(e, "operand").unwrap()));
                Json::Object(o)
            }
            "update_expression" => {
                let t = doc.text(e);
                let op_s = if t.starts_with("++") {
                    "++pre"
                } else if t.starts_with("--") {
                    "--pre"
                } else if t.ends_with("++") {
                    "post++"
                } else {
                    "post--"
                };
                let mut o = Obj::new();
                o.insert("un".into(), op_s.into());
                o.insert("e".into(), self.expr(kids(e)[0]));
                Json::Object(o)
            }
            "assignment_expression" => {
                let mut o = Obj::new();
                o.insert("assign".into(), doc.ftext(e, "operator").into());
                o.insert("target".into(), self.expr(field(e, "left").unwrap()));
                o.insert("expr".into(), self.expr(field(e, "right").unwrap()));
                Json::Object(o)
            }
            "ternary_expression" => {
                let mut o = Obj::new();
                o.insert("tern".into(), self.expr(field(e, "condition").unwrap()));
                o.insert("then".into(), self.expr(field(e, "consequence").unwrap()));
                o.insert("else".into(), self.expr(field(e, "alternative").unwrap()));
                Json::Object(o)
            }
            "cast_expression" => {
                let mut o = Obj::new();
                let types: Vec<String> = fields(e, "type").iter().map(|t| type_str(doc, *t)).collect();
                o.insert("cast".into(), types.join(" & ").into());
                o.insert("e".into(), self.expr(field(e, "value").unwrap()));
                Json::Object(o)
            }
            "instanceof_expression" => {
                let mut o = Obj::new();
                let right = field(e, "right").or_else(|| field(e, "pattern"));
                o.insert("instanceof".into(), right.map(|r| type_str(doc, r)).unwrap_or_default().into());
                o.insert("e".into(), self.expr(field(e, "left").unwrap()));
                Json::Object(o)
            }
            "array_access" => {
                let mut o = Obj::new();
                o.insert("index".into(), self.expr(field(e, "index").unwrap()));
                o.insert("of".into(), self.expr(field(e, "array").unwrap()));
                Json::Object(o)
            }
            "array_creation_expression" => {
                let mut o = Obj::new();
                o.insert("new_array".into(), field(e, "type").map(|t| type_str(doc, t)).unwrap_or_default().into());
                let mut dims = Vec::new();
                for d in fields(e, "dimensions") {
                    if d.kind() == "dimensions_expr" {
                        let v = match kids(d).into_iter().next() {
                            Some(x) => self.expr(x),
                            None => Json::Null,
                        };
                        dims.push(v);
                    } else {
                        for _ in 0..doc.text(d).matches('[').count() {
                            dims.push(Json::Null);
                        }
                    }
                }
                o.insert("dims".into(), Json::Array(dims));
                let init = match field(e, "value") {
                    Some(v) => self.expr(v),
                    None => Json::Null,
                };
                o.insert("init".into(), init);
                Json::Object(o)
            }
            "array_initializer" => {
                let mut o = Obj::new();
                o.insert("new_array".into(), Json::Null);
                let items: Vec<Json> = kids(e).into_iter().map(|v| self.expr(v)).collect();
                o.insert("init".into(), Json::Array(items));
                Json::Object(o)
            }
            "lambda_expression" => self.lambda(e),
            "method_reference" => {
                let mut o = Obj::new();
                o.insert("method_ref".into(), expr_str(doc, e).into());
                let mut w = e.walk();
                let last = e.children(&mut w).last().unwrap();
                let (l, c) = if last.kind() != "new" { (line(last), col(last)) } else { (line(e), col(e)) };
                if let Some(cs) = self.sk.call_site(&doc.rel, l, c) {
                    self.call_sites_seen.push(cs.to_string());
                    o.insert("call".into(), cs.into());
                }
                Json::Object(o)
            }
            "this" => json!({"this": true}),
            "super" => json!({"super": true}),
            "class_literal" => json!({"class": kids(e).first().map(|t| type_str(doc, *t)).unwrap_or_default()}),
            _ => {
                // страховка: неразобранное выражение; вызовы внутри всё равно привязываем
                let mut o = Obj::new();
                o.insert("text".into(), expr_str(doc, e).into());
                let calls: Vec<Node> = ast::descendants(e).into_iter().filter(|n| n.kind() == "method_invocation").collect();
                let inner: Vec<Json> = calls.into_iter().map(|c| self.method_call(c)).collect();
                if !inner.is_empty() {
                    o.insert("calls".into(), Json::Array(inner));
                }
                Json::Object(o)
            }
        }
    }

    fn name(&mut self, n: Node<'a>) -> Json {
        let id = self.doc.text(n).to_string();
        if self.is_local(&id) {
            return name_ref(&id, "local");
        }
        if self.params.contains(&id) {
            return name_ref(&id, "param");
        }
        if self.fields.contains(&id) {
            for t in &self.enclosing {
                if let Some(c) = self.project.constant(t, &id) {
                    return json!({"const": format!("{t}.{id}"), "value": c.clone()});
                }
                if self.project.enum_constant(t, &id).is_some() {
                    return self.enum_node(&t.clone(), &id);
                }
            }
            return name_ref(&id, "field");
        }
        if let Some(st) = self.static_import(&id) {
            return st;
        }
        let suffix = format!(".{id}");
        let imported = self.doc.imports.iter().any(|imp| imp.is_static && (imp.asterisk || imp.name.ends_with(&suffix)));
        let r = if imported {
            "static"
        } else if id.chars().next().is_some_and(char::is_uppercase) {
            "type"
        } else {
            "unknown"
        };
        name_ref(&id, r)
    }

    /// Константа по статическому импорту: enum или `static final` поле типа проекта.
    fn static_import(&self, id: &str) -> Option<Json> {
        for imp in self.doc.imports.iter().filter(|i| i.is_static) {
            let type_name = if imp.asterisk {
                Some(imp.name.as_str())
            } else if imp.name.ends_with(&format!(".{id}")) {
                Some(&imp.name[..imp.name.len() - id.len() - 1])
            } else {
                None
            };
            let Some(type_name) = type_name else { continue };
            let simple = type_name.rsplit('.').next().unwrap_or(type_name);
            let Some(fqn) = self.project.resolve_type(simple, self.doc) else { continue };
            if self.project.enum_constant(&fqn, id).is_some() {
                return Some(self.enum_node(&fqn, id));
            }
            if let Some(c) = self.project.constant(&fqn, id) {
                return Some(json!({"const": format!("{fqn}.{id}"), "value": c.clone()}));
            }
        }
        None
    }

    fn field_access(&mut self, fa: Node<'a>) -> Json {
        let scope = field(fa, "object").unwrap();
        let name = self.doc.ftext(fa, "field");
        if let Some(t) = self.type_of(scope) {
            if self.project.enum_constant(&t, name).is_some() {
                return self.enum_node(&t, name);
            }
            if let Some(c) = self.project.constant(&t, name) {
                return json!({"const": format!("{t}.{name}"), "value": c.clone()});
            }
        }
        let mut o = Obj::new();
        o.insert("field".into(), name.into());
        o.insert("of".into(), self.expr(scope));
        Json::Object(o)
    }

    /// FQN типа проекта, если выражение — имя типа (`OrderStatus` или полное `com.example.OrderStatus`).
    fn type_of(&self, scope: Node<'a>) -> Option<String> {
        let scope = if scope.kind() == "parenthesized_expression" { ast::unparen(scope) } else { scope };
        match scope.kind() {
            "identifier" => {
                let id = self.doc.text(scope);
                if self.is_local(id) || self.params.contains(id) || self.fields.contains(id) || !id.chars().next().is_some_and(char::is_uppercase) {
                    return None;
                }
                self.project.resolve_type(id, self.doc)
            }
            "field_access" => {
                let simple = self.doc.ftext(scope, "field");
                if !simple.chars().next().is_some_and(char::is_uppercase) {
                    return None;
                }
                let fqn = self.project.resolve_type(simple, self.doc)?;
                (fqn.replace('$', ".") == expr_str(self.doc, scope)).then_some(fqn)
            }
            _ => None,
        }
    }

    fn enum_node(&self, fqn: &str, constant: &str) -> Json {
        let args = self.project.enum_constant(fqn, constant).cloned().unwrap_or_default();
        json!({"enum": fqn, "constant": constant, "args": args})
    }

    fn method_call(&mut self, mc: Node<'a>) -> Json {
        let doc = self.doc;
        let mut o = Obj::new();
        let scope = field(mc, "object");
        let recv = match scope {
            Some(s) => self.expr(s),
            None => Json::Null,
        };
        let name_node = field(mc, "name").unwrap();
        let name = doc.text(name_node);
        let owner: Option<String> = if scope.is_none() || scope.is_some_and(|s| s.kind() == "this") {
            Some(self.method.owner.clone())
        } else if let Some(e) = recv.get("enum").and_then(Json::as_str) {
            Some(e.to_string())
        } else if recv.get("ref").and_then(Json::as_str) == Some("type") {
            self.project.resolve_type(recv["name"].as_str().unwrap_or(""), doc)
        } else {
            None
        };
        let args = argument_nodes(mc);
        let target = owner.as_deref().and_then(|ow| self.sk.unique_method(ow, name, args.len()));
        self.put_call_id(&mut o, line(name_node), col(name_node), target);
        o.insert("callee".into(), name.into());
        o.insert("recv".into(), recv);
        let a: Vec<Json> = args.into_iter().map(|x| self.expr(x)).collect();
        o.insert("args".into(), Json::Array(a));
        Json::Object(o)
    }

    fn object_creation(&mut self, oce: Node<'a>) -> Json {
        let doc = self.doc;
        let mut o = Obj::new();
        let ty = field(oce, "type").unwrap();
        o.insert("new".into(), type_str(doc, ty).into());
        let fqn = self.type_fqn(&type_name_with_scope(doc, ty));
        if let Some(f) = &fqn {
            o.insert("fqn".into(), f.clone().into());
        }
        let args = argument_nodes(oce);
        let ctor = fqn.as_deref().and_then(|f| self.sk.unique_method(f, "<init>", args.len()));
        if let Some(cs) = self.sk.call_site(&doc.rel, line(oce), col(oce)) {
            self.call_sites_seen.push(cs.to_string());
            o.insert("call".into(), cs.into());
            if let Some(c) = ctor {
                if !self.sk.has_edges(cs) {
                    o.insert("target".into(), c.id.clone().into());
                }
            }
        }
        let a: Vec<Json> = args.into_iter().map(|x| self.expr(x)).collect();
        o.insert("args".into(), Json::Array(a));
        if kids(oce).iter().any(|k| k.kind() == "class_body") {
            let anon = self.sk.anonymous_type(&doc.rel, line(oce)).unwrap_or("unresolved");
            o.insert("anon".into(), anon.into());
        }
        Json::Object(o)
    }

    /// Полное имя типа, как написан в `new`: тип проекта (вложенные через `$`), иначе явный импорт,
    /// иначе уже полное имя; `None` — не определить (`java.lang`, импорт со звёздочкой).
    fn type_fqn(&self, written: &str) -> Option<String> {
        let simple = written.rsplit('.').next().unwrap_or(written);
        let project = self.project.resolve_type(simple, self.doc);
        if let Some(p) = &project {
            if written == simple || p.replace('$', ".") == written {
                return project;
            }
        }
        if written.contains('.') {
            return Some(written.to_string());
        }
        let suffix = format!(".{written}");
        self.doc.imports.iter().find(|i| !i.is_static && !i.asterisk && i.name.ends_with(&suffix)).map(|i| i.name.clone())
    }

    fn put_call_id(&mut self, o: &mut Obj, line: usize, col: usize, target: Option<&MethodNode>) {
        if let Some(cs) = self.sk.call_site(&self.doc.rel, line, col) {
            self.call_sites_seen.push(cs.to_string());
            o.insert("call".into(), cs.into());
            // у call_site без рёбер скелета (вызовы на enum-константах) цель даёт IR
            if let Some(t) = target {
                if !self.sk.has_edges(cs) {
                    o.insert("target".into(), t.id.clone().into());
                }
            }
        } else {
            self.ir_calls += 1;
            o.insert("call".into(), format!("ircall:{}@{}:{}", self.method.id, line, col).into());
            if let Some(t) = target {
                o.insert("target".into(), t.id.clone().into());
            }
        }
    }

    fn lambda(&mut self, le: Node<'a>) -> Json {
        let doc = self.doc;
        let mut inner = Obj::new();
        inner.insert("line".into(), line(le).into());
        inner.insert("col".into(), col(le).into());
        let mut names = HashSet::new();
        let mut ps = Vec::new();
        if let Some(p) = field(le, "parameters") {
            let pn: Vec<String> = match p.kind() {
                "identifier" => vec![doc.text(p).to_string()],
                "inferred_parameters" => kids(p).iter().map(|k| doc.text(*k).to_string()).collect(),
                _ => ast::parameter_nodes(le).iter().map(|k| ast::parameter_name(doc, *k).to_string()).collect(),
            };
            for n in pn {
                ps.push(Json::String(n.clone()));
                names.insert(n);
            }
        }
        inner.insert("params".into(), Json::Array(ps));
        self.locals.push(names);
        let body = field(le, "body").unwrap();
        let b = if body.kind() == "block" {
            self.block(body)
        } else {
            let mut r = op("return", body);
            r.insert("expr".into(), self.expr(body));
            Json::Array(vec![Json::Object(r)])
        };
        inner.insert("body".into(), b);
        self.locals.pop();
        let mut o = Obj::new();
        o.insert("lambda".into(), Json::Object(inner));
        Json::Object(o)
    }
}

//! Слой над tree-sitter-java: файл с деревом, импорты, позиции в системе скелета и узлы в терминах JavaParser.
//!
//! Java-версия опирается на AST JavaParser (`ExpressionStmt(VariableDeclarationExpr)`, `EnclosedExpr`, `getBegin()`).
//! Здесь те же понятия поверх tree-sitter: условие `if`/`while` без скобок оператора, «логический родитель»
//! без `argument_list`, имена типов и выражений в той записи, как их печатает `Node.toString()` JavaParser.

use tree_sitter::{Node, Parser, Tree};

pub struct Import {
    /// Имя без `.*`.
    pub name: String,
    pub is_static: bool,
    pub asterisk: bool,
}

/// Разобранный файл проекта.
pub struct Doc {
    pub rel: String,
    pub module: String,
    pub src: Vec<u8>,
    pub tree: Tree,
    pub pkg: String,
    pub imports: Vec<Import>,
}

/// Единица разбора (метод, класс) под защитой: паника на непривычном синтаксисе (узлы ERROR/MISSING tree-sitter)
/// пропускает только её, с сообщением, а не роняет весь разбор и с ним IR всего проекта.
pub fn guarded<T>(what: impl FnOnce() -> String, f: impl FnOnce() -> T) -> Option<T> {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(f)) {
        Ok(v) => Some(v),
        Err(_) => {
            eprintln!("archonity-parse: пропущено после ошибки разбора: {}", what());
            None
        }
    }
}

pub fn new_parser() -> Parser {
    let mut p = Parser::new();
    p.set_language(&tree_sitter_java::LANGUAGE.into()).expect("грамматика Java");
    p
}

impl Doc {
    pub fn parse(parser: &mut Parser, rel: String, module: String, src: Vec<u8>) -> Option<Doc> {
        let tree = parser.parse(&src, None)?;
        let mut doc = Doc { rel, module, src, tree, pkg: String::new(), imports: Vec::new() };
        let root = doc.tree.root_node();
        let mut pkg = String::new();
        let mut imports = Vec::new();
        for c in kids(root) {
            match c.kind() {
                "package_declaration" => {
                    if let Some(n) = kids(c).into_iter().find(|k| matches!(k.kind(), "scoped_identifier" | "identifier")) {
                        pkg = doc.text(n).to_string();
                    }
                }
                "import_declaration" => {
                    let mut is_static = false;
                    let mut asterisk = false;
                    let mut name = String::new();
                    let mut w = c.walk();
                    for ch in c.children(&mut w) {
                        match ch.kind() {
                            "static" => is_static = true,
                            "asterisk" => asterisk = true,
                            "scoped_identifier" | "identifier" => name = doc.text(ch).to_string(),
                            _ => {}
                        }
                    }
                    imports.push(Import { name, is_static, asterisk });
                }
                _ => {}
            }
        }
        doc.pkg = pkg;
        doc.imports = imports;
        Some(doc)
    }

    pub fn root(&self) -> Node<'_> {
        self.tree.root_node()
    }

    pub fn text(&self, n: Node) -> &str {
        n.utf8_text(&self.src).unwrap_or("")
    }

    /// Текст поля узла (`name`, `type`...) или пустая строка.
    pub fn ftext(&self, n: Node, field: &str) -> &str {
        n.child_by_field_name(field).map(|c| self.text(c)).unwrap_or("")
    }
}

pub fn is_comment(n: Node) -> bool {
    matches!(n.kind(), "line_comment" | "block_comment")
}

/// Именованные дети без комментариев.
pub fn kids(n: Node) -> Vec<Node> {
    let mut w = n.walk();
    n.named_children(&mut w).filter(|c| !is_comment(*c)).collect()
}

/// Дети поля (повторяющегося) без комментариев.
pub fn fields<'a>(n: Node<'a>, field: &str) -> Vec<Node<'a>> {
    let mut w = n.walk();
    n.children_by_field_name(field, &mut w).filter(|c| c.is_named() && !is_comment(*c)).collect()
}

pub fn field<'a>(n: Node<'a>, name: &str) -> Option<Node<'a>> {
    n.child_by_field_name(name)
}

/// Строка начала узла (1-based), как `getBegin().line` JavaParser.
pub fn line(n: Node) -> usize {
    n.start_position().row + 1
}

/// Колонка начала узла в системе скелета: 1-based смещение в байтах UTF-8.
pub fn col(n: Node) -> usize {
    n.start_position().column + 1
}

pub fn is_type_decl(kind: &str) -> bool {
    matches!(kind, "class_declaration" | "interface_declaration" | "enum_declaration" | "annotation_type_declaration" | "record_declaration")
}

/// `ClassOrInterfaceDeclaration` JavaParser: класс или интерфейс.
pub fn is_class_or_interface(kind: &str) -> bool {
    matches!(kind, "class_declaration" | "interface_declaration")
}

pub fn is_callable(kind: &str) -> bool {
    matches!(kind, "method_declaration" | "constructor_declaration")
}

/// Узлы-выражения JavaParser (родители выражений на пути вверх).
pub fn is_expression(kind: &str) -> bool {
    matches!(
        kind,
        "binary_expression"
            | "unary_expression"
            | "update_expression"
            | "assignment_expression"
            | "ternary_expression"
            | "cast_expression"
            | "instanceof_expression"
            | "parenthesized_expression"
            | "method_invocation"
            | "field_access"
            | "array_access"
            | "object_creation_expression"
            | "array_creation_expression"
            | "array_initializer"
            | "lambda_expression"
            | "method_reference"
            | "class_literal"
            | "switch_expression"
    )
}

/// Родитель в смысле JavaParser: `argument_list`, `dimensions_expr` и т. п. не считаются узлами.
pub fn parent(n: Node) -> Option<Node> {
    let mut p = n.parent()?;
    while matches!(p.kind(), "argument_list" | "dimensions_expr" | "inferred_parameters") {
        p = p.parent()?;
    }
    Some(p)
}

/// Условие `if`/`while`/`do`/`switch`/`synchronized` без скобок оператора.
pub fn cond_inner(n: Node) -> Option<Node> {
    unparen_once(n)
}

fn unparen_once(n: Node) -> Option<Node> {
    if n.kind() == "parenthesized_expression" {
        kids(n).into_iter().next()
    } else {
        Some(n)
    }
}

/// Условие оператора: поле `condition`, снятая скобка оператора.
pub fn stmt_condition(stmt: Node) -> Option<Node> {
    field(stmt, "condition").and_then(cond_inner)
}

/// Скобки выражения (`EnclosedExpr`) снимаются любой глубины.
pub fn unparen(mut n: Node) -> Node {
    while n.kind() == "parenthesized_expression" {
        match kids(n).into_iter().next() {
            Some(i) => n = i,
            None => break,
        }
    }
    n
}

pub fn has_modifier(decl: Node, word: &str) -> bool {
    let Some(m) = kids(decl).into_iter().find(|c| c.kind() == "modifiers") else { return false };
    let mut w = m.walk();
    let found = m.children(&mut w).any(|c| c.kind() == word);
    found
}

/// Аннотации объявления (`modifiers`): `(имя как написано, узел)`.
pub fn annotations<'a>(doc: &Doc, decl: Node<'a>) -> Vec<(String, Node<'a>)> {
    let Some(m) = kids(decl).into_iter().find(|c| c.kind() == "modifiers") else { return Vec::new() };
    kids(m)
        .into_iter()
        .filter(|a| matches!(a.kind(), "marker_annotation" | "annotation"))
        .map(|a| (doc.ftext(a, "name").to_string(), a))
        .collect()
}

pub fn annotation<'a>(doc: &Doc, decl: Node<'a>, name: &str) -> Option<Node<'a>> {
    annotations(doc, decl).into_iter().find(|(n, _)| n == name).map(|(_, a)| a)
}

/// Значение атрибута строкой-литералом: `@A(name = "x")` или `@A("x")` для `value`.
pub fn annotation_attr(doc: &Doc, a: Node, attr: &str) -> Option<String> {
    let args = field(a, "arguments")?;
    let items = kids(args);
    if items.len() == 1 && items[0].kind() == "string_literal" {
        return if attr == "value" { Some(string_value(doc, items[0])) } else { None };
    }
    for p in items {
        if p.kind() == "element_value_pair" && doc.ftext(p, "key") == attr {
            let v = field(p, "value")?;
            if v.kind() == "string_literal" {
                return Some(string_value(doc, v));
            }
        }
    }
    None
}

// ----------------------------------------------------------------------
// Литералы
// ----------------------------------------------------------------------

/// `StringLiteralExpr.asString()`: значение без кавычек, escape-последовательности раскрыты; текстовый блок — построчно.
pub fn string_value(doc: &Doc, n: Node) -> String {
    let t = doc.text(n);
    if let Some(body) = t.strip_prefix("\"\"\"") {
        return text_block(body.strip_suffix("\"\"\"").unwrap_or(body));
    }
    let inner = t.strip_prefix('"').and_then(|s| s.strip_suffix('"')).unwrap_or(t);
    unescape(inner)
}

/// Текстовый блок по правилам JLS: убрать первую строку, общий отступ и хвостовые пробелы, раскрыть escape-последовательности.
fn text_block(body: &str) -> String {
    let body = body.split_once('\n').map(|(_, r)| r).unwrap_or("");
    let lines: Vec<&str> = body.split('\n').map(|l| l.strip_suffix('\r').unwrap_or(l)).collect();
    let last = lines.len().saturating_sub(1);
    let indent = lines
        .iter()
        .enumerate()
        .filter(|(i, l)| *i == last || !l.trim().is_empty())
        .map(|(_, l)| l.len() - l.trim_start().len())
        .min()
        .unwrap_or(0);
    let stripped: Vec<String> = lines
        .iter()
        .map(|l| if l.trim().is_empty() { String::new() } else { l[indent.min(l.len())..].trim_end().to_string() })
        .collect();
    unescape(&stripped.join("\n"))
}

/// Java-escape: `\n \t \b \r \f \s \" \' \\`, восьмеричные и `\uXXXX`, продолжение строки `\<newline>`.
pub fn unescape(s: &str) -> String {
    let chars: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c != '\\' || i + 1 >= chars.len() {
            out.push(c);
            i += 1;
            continue;
        }
        i += 1;
        match chars[i] {
            'n' => out.push('\n'),
            't' => out.push('\t'),
            'b' => out.push('\x08'),
            'r' => out.push('\r'),
            'f' => out.push('\x0c'),
            's' => out.push(' '),
            '"' => out.push('"'),
            '\'' => out.push('\''),
            '\\' => out.push('\\'),
            '\n' => {}
            'u' => {
                while i < chars.len() && chars[i] == 'u' {
                    i += 1;
                }
                let hex: String = chars[i..(i + 4).min(chars.len())].iter().collect();
                if let Some(ch) = u32::from_str_radix(&hex, 16).ok().and_then(char::from_u32) {
                    out.push(ch);
                }
                i += 3;
            }
            d @ '0'..='7' => {
                let mut v = d.to_digit(8).unwrap();
                let max = if d <= '3' { 2 } else { 1 };
                let mut n = 0;
                while n < max && i + 1 < chars.len() && chars[i + 1].is_digit(8) {
                    i += 1;
                    v = v * 8 + chars[i].to_digit(8).unwrap();
                    n += 1;
                }
                out.push(char::from_u32(v).unwrap_or('?'));
            }
            other => {
                out.push('\\');
                out.push(other);
            }
        }
        i += 1;
    }
    out
}

/// Числовой литерал: `(значение, это long)` для целых; `None`, если не целый.
pub fn parse_integer(text: &str) -> Option<(i64, bool)> {
    let t: String = text.chars().filter(|c| *c != '_').collect();
    let is_long = t.ends_with('l') || t.ends_with('L');
    let t = if is_long { &t[..t.len() - 1] } else { &t[..] };
    let (radix, digits) = if let Some(r) = t.strip_prefix("0x").or_else(|| t.strip_prefix("0X")) {
        (16, r)
    } else if let Some(r) = t.strip_prefix("0b").or_else(|| t.strip_prefix("0B")) {
        (2, r)
    } else if t.len() > 1 && t.starts_with('0') {
        (8, &t[1..])
    } else {
        (10, t)
    };
    let v = u64::from_str_radix(digits, radix).ok()?;
    if is_long {
        Some((v as i64, true))
    } else {
        Some((v as u32 as i32 as i64, false))
    }
}

pub fn parse_double(text: &str) -> f64 {
    let t: String = text.chars().filter(|c| *c != '_').collect();
    let t = t.trim_end_matches(|c| matches!(c, 'f' | 'F' | 'd' | 'D'));
    t.parse().unwrap_or(f64::NAN)
}

// ----------------------------------------------------------------------
// Типы и выражения как печатает JavaParser
// ----------------------------------------------------------------------

/// `Type.asString()`: имя с областью и обобщениями без пробелов после запятой (`Map<String,List<Order>>`, `int[]`).
pub fn type_str(doc: &Doc, n: Node) -> String {
    type_text(doc, n, false)
}

/// `Type.toString()` pretty-printer: аргументы обобщения через `, `.
pub fn type_pretty(doc: &Doc, n: Node) -> String {
    type_text(doc, n, true)
}

fn type_text(doc: &Doc, n: Node, spaced: bool) -> String {
    let rec = |x: Node| type_text(doc, x, spaced);
    match n.kind() {
        "generic_type" => {
            let ks = kids(n);
            let base = ks.first().map(|b| rec(*b)).unwrap_or_default();
            let args = ks.iter().find(|k| k.kind() == "type_arguments").map(|a| type_args_text(doc, *a, spaced)).unwrap_or_default();
            format!("{base}{args}")
        }
        "scoped_type_identifier" => kids(n).iter().map(|k| rec(*k)).collect::<Vec<_>>().join("."),
        "array_type" => {
            let el = field(n, "element").map(|e| rec(e)).unwrap_or_default();
            let dims = field(n, "dimensions").map(|d| doc.text(d).matches('[').count()).unwrap_or(0);
            format!("{el}{}", "[]".repeat(dims))
        }
        "wildcard" => {
            let ks = kids(n);
            let bound = ks.iter().find(|k| !matches!(k.kind(), "marker_annotation" | "annotation"));
            let mut w = n.walk();
            let kw = n.children(&mut w).find(|c| matches!(c.kind(), "extends" | "super")).map(|c| c.kind().to_string());
            match (kw, bound) {
                (Some(k), Some(b)) => format!("? {k} {}", rec(*b)),
                _ => "?".to_string(),
            }
        }
        "annotated_type" => kids(n).iter().rev().find(|k| !matches!(k.kind(), "marker_annotation" | "annotation")).map(|k| rec(*k)).unwrap_or_default(),
        "catch_type" => kids(n).iter().map(|k| rec(*k)).collect::<Vec<_>>().join(" | "),
        _ => doc.text(n).to_string(),
    }
}

fn type_args_text(doc: &Doc, a: Node, spaced: bool) -> String {
    let items: Vec<String> = kids(a).iter().map(|k| type_text(doc, *k, spaced)).collect();
    format!("<{}>", items.join(if spaced { ", " } else { "," }))
}
/// Имя класса без области и обобщений (`ClassOrInterfaceType.getNameAsString()`).
pub fn type_simple_name(doc: &Doc, n: Node) -> String {
    match n.kind() {
        "generic_type" => kids(n).first().map(|b| type_simple_name(doc, *b)).unwrap_or_default(),
        "scoped_type_identifier" => kids(n).last().map(|b| type_simple_name(doc, *b)).unwrap_or_default(),
        _ => doc.text(n).to_string(),
    }
}

/// `getNameWithScope()`: `a.b.C` без обобщений.
pub fn type_name_with_scope(doc: &Doc, n: Node) -> String {
    match n.kind() {
        "generic_type" => kids(n).first().map(|b| type_name_with_scope(doc, *b)).unwrap_or_default(),
        "scoped_type_identifier" => kids(n).iter().map(|k| type_name_with_scope(doc, *k)).collect::<Vec<_>>().join("."),
        _ => doc.text(n).to_string(),
    }
}

/// Аргументы типа `generic_type` (пусто — нет обобщений).
pub fn type_arguments<'a>(n: Node<'a>) -> Vec<Node<'a>> {
    if n.kind() != "generic_type" {
        return Vec::new();
    }
    kids(n).into_iter().find(|k| k.kind() == "type_arguments").map(kids).unwrap_or_default()
}

/// Тип, объявленный у переменной: у `int x[]` добавляются измерения declarator.
pub fn declarator_type(doc: &Doc, decl: Node, vd: Node) -> String {
    let base = field(decl, "type").map(|t| type_str(doc, t)).unwrap_or_default();
    let dims = field(vd, "dimensions").map(|d| doc.text(d).matches('[').count()).unwrap_or(0);
    format!("{base}{}", "[]".repeat(dims))
}

/// Печать выражения как `Node.toString()` JavaParser (однострочные формы; блоки и тела анонимных классов — исходным текстом).
pub fn expr_str(doc: &Doc, n: Node) -> String {
    match n.kind() {
        "parenthesized_expression" => format!("({})", kids(n).first().map(|i| expr_str(doc, *i)).unwrap_or_default()),
        "binary_expression" => format!(
            "{} {} {}",
            field(n, "left").map(|x| expr_str(doc, x)).unwrap_or_default(),
            doc.ftext(n, "operator"),
            field(n, "right").map(|x| expr_str(doc, x)).unwrap_or_default()
        ),
        "unary_expression" => format!("{}{}", doc.ftext(n, "operator"), field(n, "operand").map(|x| expr_str(doc, x)).unwrap_or_default()),
        "update_expression" => {
            let ks = kids(n);
            let operand = ks.first().map(|x| expr_str(doc, *x)).unwrap_or_default();
            let t = doc.text(n);
            let op = if t.starts_with("++") { "++" } else if t.starts_with("--") { "--" } else if t.ends_with("++") { "++" } else { "--" };
            if t.starts_with("++") || t.starts_with("--") { format!("{op}{operand}") } else { format!("{operand}{op}") }
        }
        "assignment_expression" => format!(
            "{} {} {}",
            field(n, "left").map(|x| expr_str(doc, x)).unwrap_or_default(),
            doc.ftext(n, "operator"),
            field(n, "right").map(|x| expr_str(doc, x)).unwrap_or_default()
        ),
        "ternary_expression" => format!(
            "{} ? {} : {}",
            field(n, "condition").map(|x| expr_str(doc, x)).unwrap_or_default(),
            field(n, "consequence").map(|x| expr_str(doc, x)).unwrap_or_default(),
            field(n, "alternative").map(|x| expr_str(doc, x)).unwrap_or_default()
        ),
        "cast_expression" => {
            let types: Vec<String> = fields(n, "type").iter().map(|t| type_pretty(doc, *t)).collect();
            format!("({}) {}", types.join(" & "), field(n, "value").map(|x| expr_str(doc, x)).unwrap_or_default())
        }
        "instanceof_expression" => {
            let right = field(n, "right").or_else(|| field(n, "pattern"));
            format!(
                "{} instanceof {}",
                field(n, "left").map(|x| expr_str(doc, x)).unwrap_or_default(),
                right.map(|r| if r.kind().ends_with("pattern") { doc.text(r).to_string() } else { type_pretty(doc, r) }).unwrap_or_default()
            )
        }
        "method_invocation" => {
            let mut s = String::new();
            if let Some(o) = field(n, "object") {
                s.push_str(&expr_str(doc, o));
                s.push('.');
            }
            if let Some(ta) = field(n, "type_arguments") {
                s.push_str(&type_args_text(doc, ta, true));
            }
            s.push_str(doc.ftext(n, "name"));
            s.push_str(&args_str(doc, n));
            s
        }
        "field_access" => format!(
            "{}.{}",
            field(n, "object").map(|x| expr_str(doc, x)).unwrap_or_default(),
            doc.ftext(n, "field")
        ),
        "array_access" => format!(
            "{}[{}]",
            field(n, "array").map(|x| expr_str(doc, x)).unwrap_or_default(),
            field(n, "index").map(|x| expr_str(doc, x)).unwrap_or_default()
        ),
        "object_creation_expression" => {
            let mut s = String::new();
            s.push_str("new ");
            if let Some(ta) = field(n, "type_arguments") {
                s.push_str(&type_args_text(doc, ta, true));
            }
            s.push_str(&field(n, "type").map(|t| type_pretty(doc, t)).unwrap_or_default());
            s.push_str(&args_str(doc, n));
            if let Some(body) = kids(n).into_iter().find(|k| k.kind() == "class_body") {
                s.push(' ');
                s.push_str(doc.text(body));
            }
            s
        }
        "array_creation_expression" => {
            let mut s = format!("new {}", field(n, "type").map(|t| type_pretty(doc, t)).unwrap_or_default());
            for d in fields(n, "dimensions") {
                if d.kind() == "dimensions_expr" {
                    s.push_str(&format!("[{}]", kids(d).first().map(|x| expr_str(doc, *x)).unwrap_or_default()));
                } else {
                    s.push_str(&"[]".repeat(doc.text(d).matches('[').count()));
                }
            }
            if let Some(v) = field(n, "value") {
                s.push(' ');
                s.push_str(&expr_str(doc, v));
            }
            s
        }
        "array_initializer" => {
            let items: Vec<String> = kids(n).iter().map(|x| expr_str(doc, *x)).collect();
            if items.is_empty() { "{}".to_string() } else { format!("{{ {} }}", items.join(", ")) }
        }
        "lambda_expression" => {
            let params = field(n, "parameters").map(|p| lambda_params_str(doc, p)).unwrap_or_default();
            let body = field(n, "body").map(|b| if b.kind() == "block" { doc.text(b).to_string() } else { expr_str(doc, b) }).unwrap_or_default();
            format!("{params} -> {body}")
        }
        "method_reference" => {
            let ks = kids(n);
            let scope = ks.first().map(|s| if s.kind().ends_with("type") || s.kind() == "type_identifier" { type_pretty(doc, *s) } else { expr_str(doc, *s) }).unwrap_or_default();
            let ident = doc.text(n).rsplit("::").next().unwrap_or("").trim();
            let targs = ks.iter().find(|k| k.kind() == "type_arguments").map(|a| type_args_text(doc, *a, true)).unwrap_or_default();
            format!("{scope}::{targs}{ident}")
        }
        "class_literal" => format!("{}.class", kids(n).first().map(|t| type_pretty(doc, *t)).unwrap_or_default()),
        _ => doc.text(n).to_string(),
    }
}

fn lambda_params_str(doc: &Doc, p: Node) -> String {
    match p.kind() {
        "identifier" => doc.text(p).to_string(),
        "inferred_parameters" => {
            let items: Vec<&str> = kids(p).iter().map(|k| doc.text(*k)).collect();
            format!("({})", items.join(", "))
        }
        _ => {
            let items: Vec<String> = kids(p)
                .iter()
                .map(|k| match k.kind() {
                    "formal_parameter" => format!("{} {}", field(*k, "type").map(|t| type_pretty(doc, t)).unwrap_or_default(), doc.ftext(*k, "name")),
                    _ => doc.text(*k).to_string(),
                })
                .collect();
            format!("({})", items.join(", "))
        }
    }
}

fn args_str(doc: &Doc, n: Node) -> String {
    let items: Vec<String> = argument_nodes(n).iter().map(|a| expr_str(doc, *a)).collect();
    format!("({})", items.join(", "))
}

/// Аргументы вызова или создания объекта.
pub fn argument_nodes(n: Node) -> Vec<Node> {
    field(n, "arguments").map(kids).unwrap_or_default()
}

/// Имена параметров (формальных, `...`, receiver не считается).
pub fn parameter_nodes(n: Node) -> Vec<Node> {
    field(n, "parameters")
        .map(|p| kids(p).into_iter().filter(|k| matches!(k.kind(), "formal_parameter" | "spread_parameter")).collect())
        .unwrap_or_default()
}

pub fn parameter_name<'a>(doc: &'a Doc, p: Node) -> &'a str {
    if p.kind() == "spread_parameter" {
        kids(p).into_iter().find(|k| k.kind() == "variable_declarator").map(|v| doc.ftext(v, "name")).unwrap_or("")
    } else {
        doc.ftext(p, "name")
    }
}

/// Тип параметра: у `T... x` — `T`.
pub fn parameter_type(doc: &Doc, p: Node) -> String {
    if p.kind() == "spread_parameter" {
        kids(p).into_iter().find(|k| !matches!(k.kind(), "modifiers" | "variable_declarator")).map(|t| type_str(doc, t)).unwrap_or_default()
    } else {
        field(p, "type").map(|t| type_str(doc, t)).unwrap_or_default()
    }
}

/// Двоичное имя типа как в ID скелета: вложенные типы через `$` (все объявления типов).
pub fn binary_name(doc: &Doc, td: Node) -> String {
    binary_name_where(doc, td, is_type_decl)
}

/// То же, но вложенность считают только объявления, прошедшие `keep`.
pub fn binary_name_where(doc: &Doc, td: Node, keep: fn(&str) -> bool) -> String {
    let mut names = Vec::new();
    let mut cur = Some(td);
    while let Some(c) = cur {
        if keep(c.kind()) {
            names.push(doc.ftext(c, "name").to_string());
        }
        cur = c.parent();
    }
    names.reverse();
    let name = names.join("$");
    if doc.pkg.is_empty() { name } else { format!("{}.{}", doc.pkg, name) }
}

/// Тело типа: члены (`class_body`, `interface_body`, `enum_body_declarations`...).
pub fn members(td: Node) -> Vec<Node> {
    let Some(body) = field(td, "body") else { return Vec::new() };
    let mut out = Vec::new();
    for k in kids(body) {
        if k.kind() == "enum_body_declarations" {
            out.extend(kids(k));
        } else {
            out.push(k);
        }
    }
    out
}

/// Поля типа (`FieldDeclaration`): в интерфейсах tree-sitter зовёт их `constant_declaration`.
pub fn field_decls(td: Node) -> Vec<Node> {
    members(td).into_iter().filter(|m| matches!(m.kind(), "field_declaration" | "constant_declaration")).collect()
}

pub fn declarators(fd: Node) -> Vec<Node> {
    fields(fd, "declarator")
}

/// Все потомки в порядке обхода в глубину (`Node.findAll`), включая сам узел.
pub fn descendants(n: Node) -> Vec<Node> {
    let mut out = Vec::new();
    let mut stack = vec![n];
    while let Some(x) = stack.pop() {
        out.push(x);
        let mut w = x.walk();
        let ch: Vec<Node> = x.named_children(&mut w).filter(|c| !is_comment(*c)).collect();
        for c in ch.into_iter().rev() {
            stack.push(c);
        }
    }
    out
}

/// Ближайший предок заданного вида (`findAncestor`).
pub fn ancestor<'a>(n: Node<'a>, pred: impl Fn(&str) -> bool) -> Option<Node<'a>> {
    let mut cur = n.parent();
    while let Some(c) = cur {
        if pred(c.kind()) {
            return Some(c);
        }
        cur = c.parent();
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn doc(src: &str) -> Doc {
        let mut p = new_parser();
        Doc::parse(&mut p, "m/src/main/java/A.java".into(), "m".into(), src.as_bytes().to_vec()).unwrap()
    }

    fn first_expr(d: &Doc) -> Node<'_> {
        let init = descendants(d.root()).into_iter().find(|n| n.kind() == "variable_declarator").unwrap();
        field(init, "value").unwrap()
    }

    #[test]
    fn unescapes() {
        assert_eq!(unescape(r"a\n\t\\A\101"), "a\n\t\\AA");
    }

    #[test]
    fn integers() {
        assert_eq!(parse_integer("0xFFFFFFFF"), Some((-1, false)));
        assert_eq!(parse_integer("1_000L"), Some((1000, true)));
        assert_eq!(parse_integer("010"), Some((8, false)));
    }

    #[test]
    fn imports_and_package() {
        let d = doc("package a.b;\nimport static x.Y.*;\nimport c.D;\nclass T {}");
        assert_eq!(d.pkg, "a.b");
        assert_eq!(d.imports.len(), 2);
        assert!(d.imports[0].is_static && d.imports[0].asterisk && d.imports[0].name == "x.Y");
        assert_eq!(d.imports[1].name, "c.D");
    }

    #[test]
    fn pretty_print_like_javaparser() {
        let d = doc("class T { void f() { Object o = a.b(x+1, (y)).c(new Foo<>(1), p ? q : r, !z, i++); } }");
        assert_eq!(expr_str(&d, first_expr(&d)), "a.b(x + 1, (y)).c(new Foo<>(1), p ? q : r, !z, i++)");
    }

    #[test]
    fn type_strings() {
        let d = doc("class T { Map<String, List<? extends A>> m; int[][] a; }");
        let fds: Vec<Node> = descendants(d.root()).into_iter().filter(|n| n.kind() == "field_declaration").collect();
        assert_eq!(type_str(&d, field(fds[0], "type").unwrap()), "Map<String,List<? extends A>>");
        assert_eq!(type_pretty(&d, field(fds[0], "type").unwrap()), "Map<String, List<? extends A>>");
        assert_eq!(type_str(&d, field(fds[1], "type").unwrap()), "int[][]");
    }
}

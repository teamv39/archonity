//! Чего ждёт успешный путь метода от результата чтения репозитория (порт `ResultExpectation`).
//!
//! Результат проверяется условием (`== null`, `isPresent()`, `isEmpty()`, `size()`). Если плечо «строка найдена»
//! всегда заканчивается ошибкой, а плечо «не найдена» нет, успешный путь ждёт пустой результат (`EMPTY`):
//! так устроены проверки «уже существует» перед созданием. Обратный случай даёт `ROWS`.
//! Ошибка плеча: `throw`, `return new Response<>(0, ...)` или `LOGGER.error/warn` перед `return`.
//! Всё остальное — `UNKNOWN`, тогда решает состояние БД на стороне движка.

use tree_sitter::Node;

use crate::ast::{self, expr_str, field, kids, line, Doc};

pub const ROWS: &str = "ROWS";
pub const EMPTY: &str = "EMPTY";
pub const UNKNOWN: &str = "UNKNOWN";

/// Полярность проверки: истинна, когда строка найдена (`Found`), или когда не найдена (`Absent`).
#[derive(Clone, Copy, PartialEq)]
enum Polarity {
    Found,
    Absent,
    Mixed,
}

/// Проверяемое: само выражение вызова или переменная.
#[derive(Clone, Copy)]
enum Subject<'a, 'v> {
    Expr(Node<'a>),
    Var(&'v str),
}

fn same(a: Node, b: Node) -> bool {
    a.id() == b.id()
}

pub fn before(a: Node, b: Node) -> bool {
    a.start_byte() < b.start_byte()
}

/// Метод или конструктор с вызовом, иначе корень файла.
pub fn enclosing_body(n: Node) -> Node {
    ast::ancestor(n, |k| k == "method_declaration")
        .or_else(|| ast::ancestor(n, |k| k == "constructor_declaration"))
        .unwrap_or_else(|| {
            let mut r = n;
            while let Some(p) = r.parent() {
                r = p;
            }
            r
        })
}

/// Возвращает `(expects, reason)`.
pub fn analyze(doc: &Doc, call: Node) -> (&'static str, String) {
    let mut result = call;
    let mut parent = call.parent();

    // Цепочка на Optional: orElseThrow()/get() требуют строку, orElse(null) даёт обычную nullable-переменную
    while let Some(chained) = parent.filter(|p| p.kind() == "method_invocation" && field(*p, "object").is_some_and(|o| same(o, result))) {
        let name = doc.ftext(chained, "name");
        if name == "orElseThrow" || name == "get" {
            return (ROWS, format!("line {}: .{}()", line(chained), name));
        }
        if name == "isPresent" || name == "isEmpty" {
            break;
        }
        if name != "orElse" {
            return (UNKNOWN, format!("chained .{name}()"));
        }
        result = chained;
        parent = chained.parent();
    }

    // Проверка прямо в условии: if (repo.find(x) == null), if (repo.find(x).isPresent())
    if let Some(direct) = enclosing_if_condition(result) {
        let cond = ast::stmt_condition(direct).unwrap();
        let p = polarity(doc, cond, Subject::Expr(result));
        return decide(doc, direct, p);
    }

    let Some(var) = assigned_variable(doc, result) else {
        return (UNKNOWN, "result not checked".to_string());
    };

    // Первое условие после вызова, проверяющее переменную
    let body = enclosing_body(call);
    let mut test: Option<Node> = None;
    for s in ast::descendants(body).into_iter().filter(|n| n.kind() == "if_statement") {
        let cond = ast::stmt_condition(s).unwrap();
        if before(call, s) && polarity(doc, cond, Subject::Var(&var)).is_some() && test.is_none_or(|t| before(s, t)) {
            test = Some(s);
        }
    }
    let Some(test) = test else {
        return (UNKNOWN, format!("variable {var} not checked"));
    };
    let p = polarity(doc, ast::stmt_condition(test).unwrap(), Subject::Var(&var));
    decide(doc, test, p)
}

fn decide(doc: &Doc, test: Node, p: Option<Polarity>) -> (&'static str, String) {
    let cond = ast::stmt_condition(test).unwrap();
    let where_ = format!("line {}: if ({})", line(test), expr_str(doc, cond));
    let p = match p {
        None | Some(Polarity::Mixed) => return (UNKNOWN, format!("{where_}: mixed condition")),
        Some(p) => p,
    };
    let then = field(test, "consequence").unwrap();
    let then_err = arm_error(doc, then);
    let else_err = if let Some(alt) = field(test, "alternative") {
        arm_error(doc, alt)
    } else if ends_abruptly(then) {
        list_error(doc, &following_statements(test))
    } else {
        false
    };
    let found_err = if p == Polarity::Found { then_err } else { else_err };
    let absent_err = if p == Polarity::Found { else_err } else { then_err };
    if found_err && !absent_err {
        return (EMPTY, format!("{where_}: found arm fails"));
    }
    if absent_err && !found_err {
        return (ROWS, format!("{where_}: absent arm fails"));
    }
    (UNKNOWN, format!("{where_}: no failing arm"))
}

/// Полярность условия относительно результата; `None` — условие результат не проверяет.
fn polarity(doc: &Doc, cond: Node, subj: Subject) -> Option<Polarity> {
    match cond.kind() {
        "parenthesized_expression" => polarity(doc, kids(cond).into_iter().next()?, subj),
        "unary_expression" if doc.ftext(cond, "operator") == "!" => {
            match polarity(doc, field(cond, "operand")?, subj) {
                Some(Polarity::Found) => Some(Polarity::Absent),
                Some(Polarity::Absent) => Some(Polarity::Found),
                p => p,
            }
        }
        "binary_expression" => {
            let op = doc.ftext(cond, "operator");
            let (left, right) = (field(cond, "left")?, field(cond, "right")?);
            if op == "||" || op == "&&" {
                let l = polarity(doc, left, subj);
                let r = polarity(doc, right, subj);
                if l.is_none() && r.is_none() {
                    return None;
                }
                // Все листья должны проверять результат и иметь одну полярность
                return match (l, r) {
                    (Some(a), Some(b)) if a == b => Some(a),
                    _ => Some(Polarity::Mixed),
                };
            }
            let other = if is_subject(doc, left, subj) {
                Some(right)
            } else if is_subject(doc, right, subj) {
                Some(left)
            } else {
                None
            };
            if other.is_some_and(|o| o.kind() == "null_literal") {
                if op == "==" {
                    return Some(Polarity::Absent);
                }
                if op == "!=" {
                    return Some(Polarity::Found);
                }
            }
            // x.size() == 0, x.size() > 0, x.size() != 0
            if size_call_on(doc, left, subj) && is_int_zero(doc, right) {
                if op == "==" || op == "<=" {
                    return Some(Polarity::Absent);
                }
                if op == ">" || op == "!=" {
                    return Some(Polarity::Found);
                }
            }
            None
        }
        "method_invocation" => {
            let scope = field(cond, "object")?;
            if is_subject(doc, scope, subj) {
                match doc.ftext(cond, "name") {
                    "isPresent" => return Some(Polarity::Found),
                    "isEmpty" => return Some(Polarity::Absent),
                    _ => {}
                }
            }
            None
        }
        _ => None,
    }
}

fn is_int_zero(doc: &Doc, n: Node) -> bool {
    n.kind() == "decimal_integer_literal" && ast::parse_integer(doc.text(n)).is_some_and(|(v, long)| !long && v == 0)
}

fn is_subject(doc: &Doc, e: Node, subj: Subject) -> bool {
    if e.kind() == "parenthesized_expression" {
        return kids(e).into_iter().next().is_some_and(|i| is_subject(doc, i, subj));
    }
    match subj {
        Subject::Expr(x) => same(e, x),
        Subject::Var(v) => e.kind() == "identifier" && doc.text(e) == v,
    }
}

fn size_call_on(doc: &Doc, e: Node, subj: Subject) -> bool {
    e.kind() == "method_invocation"
        && doc.ftext(e, "name") == "size"
        && field(e, "object").is_some_and(|s| is_subject(doc, s, subj))
}

/// `if`, в условии которого стоит выражение (через бинарные/логические операторы и вызовы `isPresent`).
fn enclosing_if_condition(e: Node) -> Option<Node> {
    let mut cur = e;
    while let Some(p) = ast::parent(cur) {
        if p.kind() == "parenthesized_expression" {
            if let Some(stmt) = p.parent().filter(|s| s.kind() == "if_statement" && field(*s, "condition").is_some_and(|c| same(c, p))) {
                return Some(stmt);
            }
        }
        if !ast::is_expression(p.kind()) {
            return None;
        }
        cur = p;
    }
    None
}

fn assigned_variable(doc: &Doc, e: Node) -> Option<String> {
    let parent = e.parent()?;
    match parent.kind() {
        "cast_expression" | "parenthesized_expression" => assigned_variable(doc, parent),
        "variable_declarator" => Some(doc.ftext(parent, "name").to_string()),
        "assignment_expression" => field(parent, "left").filter(|l| l.kind() == "identifier").map(|l| doc.text(l).to_string()),
        _ => None,
    }
}

// ----------------------------------------------------------------------
// Плечо с ошибкой
// ----------------------------------------------------------------------

fn statements(s: Node) -> Vec<Node> {
    if matches!(s.kind(), "block" | "constructor_body") { kids(s) } else { vec![s] }
}

pub fn arm_error(doc: &Doc, s: Node) -> bool {
    if s.kind() == "block" {
        return list_error(doc, &kids(s));
    }
    if s.kind() == "if_statement" {
        return match field(s, "alternative") {
            Some(a) => arm_error(doc, field(s, "consequence").unwrap()) && arm_error(doc, a),
            None => false,
        };
    }
    list_error(doc, &[s])
}

/// Последовательность операторов — путь отказа: `throw`, `return new Response<>(0, ...)` или `LOGGER.error/warn`
/// на верхнем уровне. Лог ошибки считается отказом и при `return new Response<>(1, ...)` («Trip already exists») и без `return`.
/// Допущение о соглашении проекта: путь отказа пишет error/warn.
fn list_error(doc: &Doc, stmts: &[Node]) -> bool {
    for &s in stmts {
        match s.kind() {
            "throw_statement" => return true,
            "expression_statement" => {
                if let Some(mc) = kids(s).into_iter().next().filter(|e| e.kind() == "method_invocation") {
                    if is_error_log(doc, mc) {
                        return true;
                    }
                }
            }
            "return_statement" => return is_error_return(doc, s),
            "if_statement" => {
                if let Some(alt) = field(s, "alternative") {
                    if ends_abruptly(field(s, "consequence").unwrap()) && ends_abruptly(alt) {
                        return arm_error(doc, s);
                    }
                }
            }
            _ => {}
        }
    }
    false
}

fn is_error_log(doc: &Doc, mc: Node) -> bool {
    let name = doc.ftext(mc, "name");
    (name == "error" || name == "warn")
        && field(mc, "object").is_some_and(|sc| expr_str(doc, sc).to_lowercase().contains("log"))
}

fn is_error_return(doc: &Doc, r: Node) -> bool {
    let Some(e) = kids(r).into_iter().next().filter(|e| e.kind() == "object_creation_expression") else { return false };
    let is_response = field(e, "type").is_some_and(|t| ast::type_simple_name(doc, t) == "Response");
    let args = ast::argument_nodes(e);
    is_response && args.first().is_some_and(|a| a.kind() == "decimal_integer_literal" && ast::parse_integer(doc.text(*a)).is_some_and(|(v, long)| !long && v == 0))
}

pub fn ends_abruptly(s: Node) -> bool {
    match s.kind() {
        "return_statement" | "throw_statement" => true,
        "block" => kids(s).into_iter().any(ends_abruptly),
        "if_statement" => match field(s, "alternative") {
            Some(a) => ends_abruptly(field(s, "consequence").unwrap()) && ends_abruptly(a),
            None => false,
        },
        _ => false,
    }
}

/// Операторы блока, идущие после данного `if` (продолжение пути, когда `then`-плечо вышло из метода).
fn following_statements(s: Node) -> Vec<Node> {
    let Some(parent) = s.parent().filter(|p| matches!(p.kind(), "block" | "constructor_body")) else { return Vec::new() };
    let all = statements(parent);
    match all.iter().position(|x| same(*x, s)) {
        Some(i) => all[i + 1..].to_vec(),
        None => Vec::new(),
    }
}

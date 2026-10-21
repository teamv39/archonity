//! Литералы IR: `{"lit": значение, "type": ...}` и значения констант.

use serde_json::{json, Map, Value as Json};
use tree_sitter::Node;

use crate::ast::{field, kids, parse_double, parse_integer, string_value, unescape, Doc};

/// Литерал JavaParser (`LiteralExpr`).
pub fn is_literal_node(n: Node) -> bool {
    matches!(
        n.kind(),
        "decimal_integer_literal"
            | "hex_integer_literal"
            | "octal_integer_literal"
            | "binary_integer_literal"
            | "decimal_floating_point_literal"
            | "hex_floating_point_literal"
            | "character_literal"
            | "string_literal"
            | "true"
            | "false"
            | "null_literal"
    )
}

/// Литерал или унарный минус литерала.
pub fn is_literal(n: Node) -> bool {
    is_literal_node(n)
        || (n.kind() == "unary_expression"
            && n.child_by_field_name("operator").is_some_and(|o| o.kind() == "-")
            && field(n, "operand").is_some_and(is_literal_node))
}

fn obj(lit: Json, ty: &str) -> Json {
    let mut m = Map::new();
    m.insert("lit".into(), lit);
    m.insert("type".into(), Json::String(ty.into()));
    Json::Object(m)
}

pub fn literal(doc: &Doc, n: Node) -> Json {
    let t = doc.text(n);
    match n.kind() {
        "decimal_integer_literal" | "hex_integer_literal" | "octal_integer_literal" | "binary_integer_literal" => {
            match parse_integer(t) {
                Some((v, true)) => obj(json!(v), "long"),
                Some((v, false)) => {
                    let decimal = n.kind() == "decimal_integer_literal";
                    let v = if decimal { t.replace('_', "").parse::<i64>().unwrap_or(v) } else { v };
                    obj(json!(v), "int")
                }
                None => obj(Json::Null, "int"),
            }
        }
        "decimal_floating_point_literal" | "hex_floating_point_literal" => {
            obj(serde_json::Number::from_f64(parse_double(t)).map(Json::Number).unwrap_or(Json::Null), "double")
        }
        "character_literal" => {
            let inner = t.strip_prefix('\'').and_then(|s| s.strip_suffix('\'')).unwrap_or(t);
            obj(Json::String(unescape(inner)), "char")
        }
        "string_literal" => obj(Json::String(string_value(doc, n)), "string"),
        "true" => obj(Json::Bool(true), "boolean"),
        "false" => obj(Json::Bool(false), "boolean"),
        _ => obj(Json::Null, "null"),
    }
}

/// Значение константы: литерал или литерал с минусом.
pub fn const_value(doc: &Doc, n: Node) -> Json {
    if n.kind() == "unary_expression" {
        let operand = field(n, "operand").or_else(|| kids(n).into_iter().last()).unwrap();
        let mut v = literal(doc, operand);
        let neg = match v.get("lit") {
            Some(Json::Number(x)) if x.is_i64() => Some(json!(-x.as_i64().unwrap())),
            Some(Json::Number(x)) => serde_json::Number::from_f64(-x.as_f64().unwrap()).map(Json::Number),
            _ => None,
        };
        if let Some(neg) = neg {
            v["lit"] = neg;
        }
        return v;
    }
    literal(doc, n)
}

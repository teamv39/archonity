//! Запись JSON как `json.dump(obj, f, ensure_ascii=False, indent=1)` Python: разделители, экранирование, `repr` чисел.

use serde_json::Value as Json;

pub use archonity_model::pyfmt::float_repr;

fn escape(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write(v: &Json, level: usize, out: &mut String) {
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                out.push_str(&i.to_string());
            } else if let Some(u) = n.as_u64() {
                out.push_str(&u.to_string());
            } else {
                out.push_str(&float_repr(n.as_f64().unwrap_or(f64::NAN)));
            }
        }
        Json::String(s) => escape(s, out),
        Json::Array(a) => {
            if a.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (k, x) in a.iter().enumerate() {
                if k > 0 {
                    out.push(',');
                }
                out.push('\n');
                out.push_str(&" ".repeat(level + 1));
                write(x, level + 1, out);
            }
            out.push('\n');
            out.push_str(&" ".repeat(level));
            out.push(']');
        }
        Json::Object(o) => {
            if o.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push('{');
            for (k, (key, x)) in o.iter().enumerate() {
                if k > 0 {
                    out.push(',');
                }
                out.push('\n');
                out.push_str(&" ".repeat(level + 1));
                escape(key, out);
                out.push_str(": ");
                write(x, level + 1, out);
            }
            out.push('\n');
            out.push_str(&" ".repeat(level));
            out.push('}');
        }
    }
}

/// `json.dumps(v, ensure_ascii=False, indent=1)`.
pub fn dumps_indent1(v: &Json) -> String {
    let mut out = String::new();
    write(v, 0, &mut out);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn indent_like_python() {
        let v: Json = serde_json::from_str(r#"{"a":[1,2.5,"é\n"],"b":{},"c":[]}"#).unwrap();
        assert_eq!(dumps_indent1(&v), "{\n \"a\": [\n  1,\n  2.5,\n  \"é\\n\"\n ],\n \"b\": {},\n \"c\": []\n}");
    }
}

/// Копия значения с ключами объектов по возрастанию (`sort_keys=True`).
pub fn sort_keys(v: &Json) -> Json {
    match v {
        Json::Object(o) => {
            let mut keys: Vec<&String> = o.keys().collect();
            keys.sort();
            Json::Object(keys.into_iter().map(|k| (k.clone(), sort_keys(&o[k]))).collect())
        }
        Json::Array(a) => Json::Array(a.iter().map(sort_keys).collect()),
        other => other.clone(),
    }
}

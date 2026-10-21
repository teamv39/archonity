//! Запись JSON как Jackson `SerializationFeature.INDENT_OUTPUT` (DefaultPrettyPrinter): `"k" : v`, отступ 2 пробела
//! только у объектов, массивы в строку (`[ a, b ]`, `[ {` ... `} ]`), пустые `[ ]` и `{ }`, числа `double` как `Double.toString`.

use serde_json::Value as Json;

/// Строка JSON с экранированием Jackson: `"`, `\`, управляющие символы (`\b\t\n\f\r`, остальные `\u00XX` заглавными).
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
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04X}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

/// `Double.toString`: десятичная запись в `[1e-3, 1e7)`, иначе `d.dddE±n`; всегда есть дробная часть.
pub fn java_double(f: f64) -> String {
    if f.is_nan() {
        return "NaN".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "Infinity" } else { "-Infinity" }.into();
    }
    if f == 0.0 {
        return if f.is_sign_negative() { "-0.0" } else { "0.0" }.into();
    }
    let sign = if f < 0.0 { "-" } else { "" };
    let a = f.abs();
    // кратчайшие цифры и десятичная экспонента: d.ddde<exp>
    let sci = format!("{a:e}");
    let (mant, exp) = sci.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let digits: String = mant.chars().filter(|c| *c != '.').collect();
    if (-3..7).contains(&exp) {
        let body = if exp >= 0 {
            let int_len = exp as usize + 1;
            if digits.len() <= int_len {
                format!("{}{}.0", digits, "0".repeat(int_len - digits.len()))
            } else {
                format!("{}.{}", &digits[..int_len], &digits[int_len..])
            }
        } else {
            format!("0.{}{}", "0".repeat((-exp - 1) as usize), digits)
        };
        format!("{sign}{body}")
    } else {
        let frac = if digits.len() > 1 { &digits[1..] } else { "0" };
        format!("{sign}{}.{frac}E{exp}", &digits[..1])
    }
}

fn write(v: &Json, depth: usize, out: &mut String) {
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                out.push_str(&i.to_string());
            } else if let Some(u) = n.as_u64() {
                out.push_str(&u.to_string());
            } else {
                out.push_str(&java_double(n.as_f64().unwrap_or(f64::NAN)));
            }
        }
        Json::String(s) => escape(s, out),
        Json::Array(a) => {
            if a.is_empty() {
                out.push_str("[ ]");
                return;
            }
            out.push_str("[ ");
            for (k, x) in a.iter().enumerate() {
                if k > 0 {
                    out.push_str(", ");
                }
                write(x, depth, out);
            }
            out.push_str(" ]");
        }
        Json::Object(o) => {
            if o.is_empty() {
                out.push_str("{ }");
                return;
            }
            out.push('{');
            for (k, (key, x)) in o.iter().enumerate() {
                if k > 0 {
                    out.push(',');
                }
                out.push('\n');
                out.push_str(&"  ".repeat(depth + 1));
                escape(key, out);
                out.push_str(" : ");
                write(x, depth + 1, out);
            }
            out.push('\n');
            out.push_str(&"  ".repeat(depth));
            out.push('}');
        }
    }
}

/// Документ целиком, без перевода строки в конце (как `ObjectMapper.writeValue`).
pub fn to_string(v: &Json) -> String {
    let mut out = String::new();
    write(v, 0, &mut out);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jackson_layout() {
        let v: Json = serde_json::from_str(r#"{"a":[1,2],"b":{},"c":[],"d":[{"x":1},{"y":[]}],"e":"\u0001é"}"#).unwrap();
        assert_eq!(
            to_string(&v),
            "{\n  \"a\" : [ 1, 2 ],\n  \"b\" : { },\n  \"c\" : [ ],\n  \"d\" : [ {\n    \"x\" : 1\n  }, {\n    \"y\" : [ ]\n  } ],\n  \"e\" : \"\\u0001é\"\n}"
        );
    }

    #[test]
    fn java_doubles() {
        assert_eq!(java_double(0.2), "0.2");
        assert_eq!(java_double(1.0), "1.0");
        assert_eq!(java_double(100.0), "100.0");
        assert_eq!(java_double(1234567.0), "1234567.0");
        assert_eq!(java_double(12345678.0), "1.2345678E7");
        assert_eq!(java_double(0.001), "0.001");
        assert_eq!(java_double(0.0001), "1.0E-4");
        assert_eq!(java_double(-2.5), "-2.5");
    }
}

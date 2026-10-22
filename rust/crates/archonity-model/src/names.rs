//! Имена: простое имя класса и `camel_to_snake` (`engine/manifest.py`).

/// Простое имя класса без пакетов и вложенных классов; `lower` — в нижнем регистре.
pub fn simple_name(fqn: Option<&str>, lower: bool) -> String {
    let s = fqn.unwrap_or("");
    let s = s.rsplit('.').next().unwrap_or("");
    let s = s.rsplit('$').next().unwrap_or("");
    if lower {
        s.to_lowercase()
    } else {
        s.to_string()
    }
}

/// Имя таблицы по умолчанию в Spring Boot: `TrainType` -> `train_type`.
pub fn camel_to_snake(name: &str) -> String {
    let s = name.replace('.', "_");
    let mut out = String::with_capacity(s.len() + 4);
    let mut prev: Option<char> = None;
    for c in s.chars() {
        if c.is_ascii_uppercase() && prev.is_some_and(|p| p.is_ascii_lowercase() || p.is_ascii_digit()) {
            out.push('_');
        }
        out.push(c);
        prev = Some(c);
    }
    out.to_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snake() {
        assert_eq!(camel_to_snake("TrainType"), "train_type");
        assert_eq!(camel_to_snake("orderId"), "order_id");
        assert_eq!(camel_to_snake("a.B"), "a_b");
        assert_eq!(camel_to_snake("ABc"), "abc");
        assert_eq!(camel_to_snake("route2Id"), "route2_id");
    }

    #[test]
    fn simple() {
        assert_eq!(simple_name(Some("a.b.Outer$Inner"), false), "Inner");
        assert_eq!(simple_name(None, true), "");
        assert_eq!(simple_name(Some("x.TripId"), true), "tripid");
    }
}

//! Форматирование и округление чисел как в Python: `repr(float)`, `round`, `str(int/float)`.

/// `repr(float)` Python: кратчайшая запись, экспонента при `exp < -4` или `exp >= 16`.
pub fn float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".to_string();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf" } else { "-inf" }.to_string();
    }
    if f == 0.0 {
        return if f.is_sign_negative() { "-0.0" } else { "0.0" }.to_string();
    }
    let sci = format!("{:e}", f.abs());
    let (mant, exp) = sci.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let digits: String = mant.chars().filter(|c| *c != '.').collect();
    let sign = if f < 0.0 { "-" } else { "" };
    let body = if !(-4..16).contains(&exp) {
        let m = if digits.len() > 1 { format!("{}.{}", &digits[..1], &digits[1..]) } else { digits.clone() };
        format!("{m}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs())
    } else if exp >= 0 {
        let e = exp as usize;
        if digits.len() <= e + 1 {
            format!("{}{}.0", digits, "0".repeat(e + 1 - digits.len()))
        } else {
            format!("{}.{}", &digits[..e + 1], &digits[e + 1..])
        }
    } else {
        format!("0.{}{}", "0".repeat((-exp - 1) as usize), digits)
    };
    format!("{sign}{body}")
}


/// Строки как `str.splitlines()` Python: разделители `\n`, `\r`, `\r\n`, `\v`, `\f`, `\x1c`-`\x1e`, `\x85`.
pub fn splitlines(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let bytes: Vec<(usize, char)> = text.char_indices().collect();
    let mut k = 0;
    while k < bytes.len() {
        let (pos, c) = bytes[k];
        if matches!(c, '\n' | '\r' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}') {
            out.push(&text[start..pos]);
            let mut next = pos + c.len_utf8();
            if c == '\r' && k + 1 < bytes.len() && bytes[k + 1].1 == '\n' {
                k += 1;
                next += 1;
            }
            start = next;
        }
        k += 1;
    }
    if start < text.len() {
        out.push(&text[start..]);
    }
    out
}

/// `round(x)` Python для float: к ближайшему целому, половина — к чётному.
pub fn round_half_even(x: f64) -> i64 {
    let r = x.round();
    if (x - x.trunc()).abs() == 0.5 {
        // ровно половина: к чётному
        let t = x.trunc();
        return if (t as i64) % 2 == 0 { t as i64 } else { r as i64 };
    }
    r as i64
}

/// `round(x, nd)` Python для float: десятичное округление точного значения, половина — к чётному.
pub fn round_digits(x: f64, nd: i64) -> f64 {
    if !x.is_finite() {
        return x;
    }
    if nd >= 0 {
        if nd > 300 {
            return x;
        }
        // Rust округляет точное десятичное значение, ничьи — к чётному, как Python
        format!("{:.*}", nd as usize, x).parse().unwrap_or(x)
    } else {
        let p = 10f64.powi((-nd) as i32);
        round_half_even(x / p) as f64 * p
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repr() {
        for (f, s) in [
            (1.0, "1.0"),
            (0.1, "0.1"),
            (1e16, "1e+16"),
            (1e15, "1000000000000000.0"),
            (1.5e-5, "1.5e-05"),
            (0.0001, "0.0001"),
            (123456.789, "123456.789"),
            (-2.5, "-2.5"),
            (1.2345678901234568e17, "1.2345678901234568e+17"),
            (100.0, "100.0"),
        ] {
            assert_eq!(float_repr(f), s, "{f}");
        }
    }

    #[test]
    fn rounding() {
        assert_eq!(round_half_even(0.5), 0);
        assert_eq!(round_half_even(1.5), 2);
        assert_eq!(round_half_even(2.5), 2);
        assert_eq!(round_half_even(-0.5), 0);
        assert_eq!(round_half_even(2.4), 2);
        assert_eq!(round_digits(2.675, 2), 2.67);
        assert_eq!(round_digits(0.125, 2), 0.12);
        assert_eq!(round_digits(1234.5, -1), 1230.0);
    }
}

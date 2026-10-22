//! Модели вызовов библиотек (JDK, Spring, Lombok) для исполнителя M4 (`engine/executor/library.py`).
//!
//! Вызов, у которого нет рёбер в скелете и нет `target` в IR, — библиотечный. Здесь считается его значение: геттеры и
//! сеттеры Lombok, String, числа, Optional, коллекции и стримы, ResponseEntity, UUID. Лямбда, переданная в библиотеку,
//! исполняется, только если библиотека её вызывает (R16). Неизвестный вызов даёт UNKNOWN; переданные в него лямбды
//! исполняются один раз (правило по умолчанию).

use archonity_io::world::fresh_uuid;
use archonity_model::pyfmt::{round_digits, round_half_even};
use archonity_model::values::*;
use chrono::{Duration, NaiveDate, NaiveDateTime};
use indexmap::IndexMap;
use regex::Regex;
use serde_json::Value as Json;

use crate::interpreter::{err, why, Frame, Interpreter, R};

/// Часы системы по контексту скелета: 15.09.2026; время — после прогрева БД.
pub fn now() -> NaiveDateTime {
    NaiveDate::from_ymd_opt(2026, 9, 15).unwrap().and_hms_opt(15, 30, 0).unwrap()
}

pub fn calendar_field(name: &str) -> Value {
    Value::Int(match name {
        "YEAR" => 1,
        "MONTH" => 2,
        "DATE" | "DAY_OF_MONTH" => 5,
        "HOUR" => 10,
        "HOUR_OF_DAY" => 11,
        "MINUTE" => 12,
        "SECOND" => 13,
        "MILLISECOND" => 14,
        _ => return Value::Unknown,
    })
}

pub fn jdk_constant(simple: &str, name: &str) -> Value {
    match (simple, name) {
        ("Integer", "MAX_VALUE") => Value::Int(2_i64.pow(31) - 1),
        ("Integer", "MIN_VALUE") => Value::Int(-(2_i64.pow(31))),
        ("Long", "MAX_VALUE") => Value::Int(i64::MAX),
        ("Long", "MIN_VALUE") => Value::Int(i64::MIN),
        ("Float", "MAX_VALUE") => Value::Float(3.4028234663852886e38),
        ("Double", "MAX_VALUE") => Value::Float(1.7976931348623157e308),
        ("Float", "MIN_VALUE") => Value::Float(1.4e-45),
        ("Double", "MIN_VALUE") => Value::Float(4.9e-324),
        ("Boolean", "TRUE") => Value::Bool(true),
        ("Boolean", "FALSE") => Value::Bool(false),
        _ => Value::Unknown,
    }
}

// --- даты ---------------------------------------------------------------------------------------------------------------

fn date_value(v: Option<NaiveDateTime>, calendar: bool) -> Value {
    Value::Date(shared(DateV { value: v, calendar }))
}

fn millis(v: NaiveDateTime) -> Value {
    Value::Int(v.and_utc().timestamp_millis())
}

fn date_call(d: &Shared<DateV>, callee: &str, args: &[Value]) -> Value {
    use chrono::{Datelike, Timelike};
    let (v, calendar) = {
        let b = d.borrow();
        (b.value, b.calendar)
    };
    let a0 = args.first().cloned().unwrap_or(Value::Unknown);
    let date_arg = |x: &Value| -> Option<Option<NaiveDateTime>> {
        match x {
            Value::Date(o) => Some(o.borrow().value),
            _ => None,
        }
    };
    if calendar {
        match callee {
            "setTime" => {
                d.borrow_mut().value = date_arg(&a0).flatten();
                return Value::Null;
            }
            "getTime" => return date_value(v, false),
            "get" => {
                let (Some(v), Some(f)) = (v, a0.as_int_or_bool()) else { return Value::Unknown };
                return match f {
                    1 => Value::Int(v.year() as i64),
                    2 => Value::Int(v.month() as i64 - 1),
                    5 => Value::Int(v.day() as i64),
                    10 => Value::Int((v.hour() % 12) as i64),
                    11 => Value::Int(v.hour() as i64),
                    12 => Value::Int(v.minute() as i64),
                    13 => Value::Int(v.second() as i64),
                    14 => Value::Int(0),
                    _ => Value::Unknown,
                };
            }
            "add" => {
                let n = args.get(1).cloned().unwrap_or(Value::Unknown);
                let (Some(v), Some(f), Some(n)) = (v, a0.as_int_or_bool(), n.as_int_or_bool()) else {
                    d.borrow_mut().value = None;
                    return Value::Null;
                };
                let delta = match f {
                    5 => Duration::try_days(n),
                    10 | 11 => Duration::try_hours(n),
                    12 => Duration::try_minutes(n),
                    13 => Duration::try_seconds(n),
                    _ => None,
                };
                d.borrow_mut().value = delta.and_then(|dl| v.checked_add_signed(dl));
                return Value::Null;
            }
            "set" => {
                d.borrow_mut().value = None;
                return Value::Null;
            }
            "getTimeInMillis" => return v.map(millis).unwrap_or(Value::Unknown),
            _ => return Value::Unknown,
        }
    }
    match callee {
        "getTime" => v.map(millis).unwrap_or(Value::Unknown),
        "before" | "after" | "compareTo" | "equals" => {
            let w = date_arg(&a0).flatten();
            let (Some(v), Some(w)) = (v, w) else { return Value::Unknown };
            match callee {
                "before" => Value::Bool(v < w),
                "after" => Value::Bool(v > w),
                "equals" => Value::Bool(v == w),
                _ => Value::Int((v > w) as i64 - (v < w) as i64),
            }
        }
        _ => Value::Unknown,
    }
}

/// Шаблон Java -> шаблон Python (`yyyy-MM-dd HH:mm:ss` -> `%Y-%m-%d %H:%M:%S`).
fn py_fmt(pattern: &str) -> String {
    let mut out = pattern.to_string();
    for (j, p) in [("yyyy", "%Y"), ("MM", "%m"), ("dd", "%d"), ("HH", "%H"), ("mm", "%M"), ("ss", "%S")] {
        out = out.replace(j, p);
    }
    out
}

/// `datetime.strptime(data, fmt)`: `%Y %m %d %H %M %S`, прочие символы — буквально; хвост данных — ошибка.
fn strptime(data: &str, fmt: &str) -> Option<NaiveDateTime> {
    let mut pat = String::from("(?i)^");
    let cs: Vec<char> = fmt.chars().collect();
    let mut i = 0;
    while i < cs.len() {
        let c = cs[i];
        if c == '%' && i + 1 < cs.len() {
            i += 1;
            pat.push_str(match cs[i] {
                'Y' => r"(?P<Y>\d\d\d\d)",
                'm' => r"(?P<m>1[0-2]|0[1-9]|[1-9])",
                'd' => r"(?P<d>3[0-1]|[1-2]\d|0[1-9]|[1-9]| [1-9])",
                'H' => r"(?P<H>2[0-3]|[0-1]\d|\d)",
                'M' => r"(?P<M>[0-5]\d|\d)",
                'S' => r"(?P<S>6[0-1]|[0-5]\d|\d)",
                '%' => "%",
                _ => return None,
            });
        } else if c.is_whitespace() {
            pat.push_str(r"\s+");
        } else {
            pat.push_str(&regex::escape(&c.to_string()));
        }
        i += 1;
    }
    let re = Regex::new(&pat).ok()?;
    let m = re.captures(data)?;
    if m.get(0)?.end() != data.len() {
        return None;
    }
    let g = |n: &str, d: u32| -> u32 { m.name(n).map(|x| x.as_str().trim().parse().unwrap_or(d)).unwrap_or(d) };
    let date = NaiveDate::from_ymd_opt(m.name("Y").map(|x| x.as_str().parse::<i32>().unwrap_or(1900)).unwrap_or(1900), g("m", 1), g("d", 1))?;
    date.and_hms_opt(g("H", 0), g("M", 0), g("S", 0))
}

/// `datetime.strftime(fmt)` для `%Y %m %d %H %M %S`.
fn strftime(v: NaiveDateTime, fmt: &str) -> String {
    use chrono::{Datelike, Timelike};
    let mut out = String::new();
    let cs: Vec<char> = fmt.chars().collect();
    let mut i = 0;
    while i < cs.len() {
        if cs[i] == '%' && i + 1 < cs.len() {
            i += 1;
            match cs[i] {
                'Y' => out.push_str(&format!("{:04}", v.year())),
                'm' => out.push_str(&format!("{:02}", v.month())),
                'd' => out.push_str(&format!("{:02}", v.day())),
                'H' => out.push_str(&format!("{:02}", v.hour())),
                'M' => out.push_str(&format!("{:02}", v.minute())),
                'S' => out.push_str(&format!("{:02}", v.second())),
                '%' => out.push('%'),
                other => {
                    out.push('%');
                    out.push(other);
                }
            }
        } else {
            out.push(cs[i]);
        }
        i += 1;
    }
    out
}

// --- JSON (Jackson, fastjson) --------------------------------------------------------------------------------------------

const JSON_WRITE: [&str; 3] = ["toJSONString", "writeValueAsString", "toJSON"];
const JSON_READ: [&str; 6] = ["parseObject", "readValue", "parseArray", "convertValue", "toJavaObject", "parse"];

/// Значение после сериализации и разбора JSON: новый объект с теми же полями.
pub fn json_copy(v: &Value, target_type: Option<&str>) -> Value {
    match v {
        Value::Json(j) => json_copy(&j.borrow().value, target_type),
        Value::Optional(o) => {
            let o = o.borrow();
            if o.value.is_null() { Value::Null } else { json_copy(&o.value, target_type) }
        }
        Value::Wrapper(w) => json_copy(&w.borrow().body, target_type),
        Value::Obj(o) => {
            let o = o.borrow();
            let fields: IndexMap<String, Value> = o.fields.iter().map(|(k, x)| (k.clone(), json_copy(x, None))).collect();
            Value::obj(target_type.or(o.ty.as_deref()), fields, o.open)
        }
        Value::List(l) => {
            let l = l.borrow();
            let mut n = ListV::new(l.items.iter().map(|x| json_copy(x, None)).collect(), l.exact);
            n.elem_type = l.elem_type.clone();
            Value::List(shared(n))
        }
        Value::Map(m) => {
            let m = m.borrow();
            let mut n = MapV::new(m.exact);
            for (k, (kk, x)) in &m.data {
                n.data.insert(k.clone(), (kk.clone(), json_copy(x, None)));
            }
            Value::Map(shared(n))
        }
        other => other.clone(),
    }
}

fn json_call(callee: &str, args: &[Value]) -> Value {
    if JSON_WRITE.contains(&callee) {
        return match args.first() {
            Some(a) => Value::Json(shared(JsonV { value: a.clone() })),
            None => Value::Unknown,
        };
    }
    if JSON_READ.contains(&callee) {
        if let Some(src @ (Value::Json(_) | Value::Obj(_) | Value::List(_) | Value::Map(_))) = args.first() {
            return json_copy(src, None);
        }
    }
    Value::Unknown
}

// --- конструкторы библиотечных классов ---------------------------------------------------------------------------------

pub fn new_library(it: &mut Interpreter, written: &str, args: &[Value]) -> Option<Value> {
    let _ = &it;
    let simple = written.rsplit('.').next().unwrap_or("");
    match simple {
        "ArrayList" | "LinkedList" | "HashSet" | "TreeSet" | "LinkedHashSet" | "Vector" => {
            let mut l = ListV::new(Vec::new(), true);
            l.is_set = simple.ends_with("Set");
            let out = shared(l);
            match args.first() {
                Some(Value::List(src)) => {
                    let (items, exact) = {
                        let s = src.borrow();
                        (s.items.clone(), s.exact)
                    };
                    out.borrow_mut().exact = exact;
                    for x in items {
                        add(&out, x);
                    }
                }
                Some(Value::Map(_)) => out.borrow_mut().exact = false,
                _ => {}
            }
            Some(Value::List(out))
        }
        "HashMap" | "TreeMap" | "LinkedHashMap" | "ConcurrentHashMap" => Some(Value::Map(shared(MapV::new(true)))),
        "HttpEntity" | "ResponseEntity" => {
            let mut body = args.first().cloned().unwrap_or(Value::Null);
            if args.len() == 1 {
                if let Value::Obj(o) = &body {
                    if o.borrow().ty.as_deref().unwrap_or("").ends_with("HttpHeaders") {
                        body = Value::Null;
                    }
                }
            }
            Some(Value::wrapper(body, if simple == "HttpEntity" { "entity" } else { "response" }))
        }
        "BigDecimal" | "Integer" | "Long" | "Double" | "Float" => Some(args.first().map(num).unwrap_or(Value::Unknown)),
        "String" | "StringBuilder" | "StringBuffer" => Some(match args.first() {
            Some(s @ Value::Str(_)) => s.clone(),
            None => Value::str(""),
            _ => Value::Unknown,
        }),
        "Random" => Some(Value::obj(Some("java.util.Random"), IndexMap::new(), true)),
        "Date" => Some(match args {
            [] => date_value(Some(now()), false),
            [a] if a.as_int_or_bool() == Some(0) => date_value(NaiveDate::from_ymd_opt(1970, 1, 1).map(|d| d.and_hms_opt(0, 0, 0).unwrap()), false),
            a if (3..=6).contains(&a.len()) && a.iter().all(|x| matches!(x, Value::Int(_))) => {
                let n: Vec<i64> = a.iter().filter_map(Value::as_int).collect();
                let dt = (|| {
                    let date = NaiveDate::from_ymd_opt((1900 + n[0]) as i32, (n[1] + 1) as u32, n[2] as u32)?;
                    date.and_hms_opt(*n.get(3).unwrap_or(&0) as u32, *n.get(4).unwrap_or(&0) as u32, *n.get(5).unwrap_or(&0) as u32)
                })();
                date_value(dt, false)
            }
            _ => date_value(None, false),
        }),
        "DecimalFormat" => {
            Some(Value::obj(Some("java.text.DecimalFormat"), [("pattern".to_string(), args.first().cloned().unwrap_or(Value::Unknown))].into_iter().collect(), false))
        }
        "SimpleDateFormat" => {
            Some(Value::obj(Some("java.text.SimpleDateFormat"), [("pattern".to_string(), args.first().cloned().unwrap_or(Value::Unknown))].into_iter().collect(), false))
        }
        "ObjectMapper" | "Gson" => Some(Value::obj(Some("com.fasterxml.jackson.databind.ObjectMapper"), IndexMap::new(), true)),
        _ => None,
    }
}

fn field_name(callee: &str, prefix: &str) -> String {
    let rest = &callee[prefix.len()..];
    let mut cs = rest.chars();
    match cs.next() {
        Some(f) => f.to_lowercase().collect::<String>() + cs.as_str(),
        None => String::new(),
    }
}

fn is_callable(v: &Value) -> bool {
    matches!(v, Value::Lambda(_) | Value::MethodRef(_))
}

fn run(it: &mut Interpreter, f: &Value, args: &[Value], fr: &mut Frame) -> R<Value> {
    if is_callable(f) {
        it.call_lambda(f, args, fr)
    } else {
        Ok(Value::Unknown)
    }
}

fn run_unknown_lambdas(it: &mut Interpreter, args: &[Value], fr: &mut Frame) -> R<()> {
    for a in args {
        if is_callable(a) {
            let n = match a {
                Value::Lambda(l) => l.borrow().params.len(),
                _ => 1,
            };
            it.call_lambda(a, &vec![Value::Unknown; n], fr)?;
        }
    }
    Ok(())
}

pub fn call_library(it: &mut Interpreter, fr: &mut Frame, callee: &str, recv: &Value, args: &[Value], e: &Json) -> R<Value> {
    if matches!(callee, "info" | "warn" | "error" | "debug" | "trace") && matches!(recv, Value::Unknown | Value::Null | Value::Obj(_) | Value::Bean(_)) {
        if matches!(recv, Value::Null | Value::Unknown | Value::Bean(_)) {
            return Ok(Value::Null);
        }
    }
    if callee == "ok" && recv.is_null() {
        return Ok(Value::wrapper(args.first().cloned().unwrap_or(Value::Null), "response"));
    }
    if callee == "getBody" {
        return Ok(match recv {
            Value::Wrapper(w) => w.borrow().body.clone(),
            _ => Value::Unknown,
        });
    }
    if let Value::TypeRef(t) = recv {
        let t = t.borrow().fqn.clone();
        return static_call(it, fr, &t, callee, args);
    }
    let recv_none = jx_get_recv_none(e);
    if recv.is_null() && recv_none {
        run_unknown_lambdas(it, args, fr)?;
        return Ok(Value::Unknown);
    }
    match recv {
        Value::Str(s) => Ok(string_call(s, callee, args)),
        Value::Concat(c) => {
            if matches!(callee, "toString" | "trim" | "intern") {
                return Ok(recv.clone());
            }
            if matches!(callee, "startsWith" | "contains" | "equals" | "endsWith") {
                if let Some(Value::Str(a0)) = args.first() {
                    let known = c.borrow().parts.first().and_then(|p| p.as_str().map(str::to_string)).unwrap_or_default();
                    if callee == "startsWith" && !known.is_empty() {
                        if known.starts_with(&**a0) {
                            return Ok(Value::Bool(true));
                        }
                        if known.chars().count() >= a0.chars().count() {
                            return Ok(Value::Bool(false));
                        }
                    }
                }
            }
            Ok(Value::Unknown)
        }
        Value::Bool(_) | Value::Int(_) | Value::Float(_) => Ok(number_call(recv, callee, args)),
        Value::Optional(o) => optional_call(it, fr, o, callee, args),
        Value::List(l) => list_call(it, fr, l, callee, args),
        Value::Map(m) => Ok(map_call(m, callee, args)),
        Value::Enum(en) => {
            match callee {
                "name" | "toString" => return Ok(Value::str(&en.borrow().constant)),
                "ordinal" => return Ok(en.borrow().ordinal.map(Value::Int).unwrap_or(Value::Unknown)),
                "equals" => return Ok(equals_value(recv, args.first().unwrap_or(&Value::Unknown)).value()),
                _ => {}
            }
            let (found, val) = project_method(it, fr, recv, callee, args)?;
            if found {
                return Ok(val);
            }
            if callee.starts_with("get") && args.is_empty() {
                return Ok(en.borrow().get(&field_name(callee, "get")));
            }
            Ok(Value::Unknown)
        }
        Value::Date(d) => Ok(date_call(d, callee, args)),
        Value::Wrapper(_) => Ok(if callee == "getStatusCode" { Value::str("OK") } else { Value::Unknown }),
        Value::Obj(o) => obj_call(it, fr, o, callee, args),
        Value::Null => Ok(Value::Unknown),
        _ => {
            run_unknown_lambdas(it, args, fr)?;
            Ok(Value::Unknown)
        }
    }
}

fn jx_get_recv_none(e: &Json) -> bool {
    archonity_io::jx::get(e, "recv").is_none_or(Json::is_null)
}

/// Метод проекта на получателе известного типа, у вызова которого в скелете нет ребра.
fn project_method(it: &mut Interpreter, fr: &mut Frame, o: &Value, callee: &str, args: &[Value]) -> R<(bool, Value)> {
    let tname = match o {
        Value::Obj(x) => x.borrow().ty.clone(),
        Value::Enum(x) => Some(x.borrow().ty.clone()),
        _ => None,
    };
    let Some(tname) = tname.filter(|t| !t.is_empty()) else { return Ok((false, Value::Null)) };
    let tid = it.types.resolve(Some(&tname), Some(&fr.module));
    let mid = it.types.method_of(tid.as_deref(), callee, Some(args.len()));
    let Some(mid) = mid.filter(|m| it.ir.contains_key(m)) else { return Ok((false, Value::Null)) };
    let unit = fr.unit.clone();
    let w = fr.why.clone();
    if crate::interpreter::unresolved_emit(&it.flags) {
        let uw = why("IR_CALL", "unresolved_receiver");
        it.sink.edge("calls", &fr.method, &mid, &uw);
        it.sink.execute(&mid, &uw, Some(format!("calls|{}|{}", fr.method, mid)));
        return Ok((true, it.invoke(&mid, o, args, &unit, &w)?));
    }
    it.sink.muted += 1;
    let r = it.invoke(&mid, o, args, &unit, &w);
    it.sink.muted -= 1;
    Ok((true, r?))
}

fn obj_call(it: &mut Interpreter, fr: &mut Frame, o: &Shared<Obj>, callee: &str, args: &[Value]) -> R<Value> {
    let ov = Value::Obj(o.clone());
    let (ty, builder) = {
        let b = o.borrow();
        (b.ty.clone(), b.fields.get("#builder").is_some_and(py_truthy))
    };
    if builder {
        if callee == "build" {
            let tid = it.types.resolve(ty.as_deref(), Some(&fr.module));
            let mut fields = IndexMap::new();
            for f in it.types.all_fields(tid.as_deref()).iter() {
                fields.insert(archonity_io::jx::str_(f, "name").unwrap_or("").to_string(), crate::interpreter::default_value_pub(f));
            }
            for (k, v) in o.borrow().fields.iter() {
                if k != "#builder" {
                    fields.insert(k.clone(), v.clone());
                }
            }
            return Ok(Value::obj(ty.as_deref(), fields, false));
        }
        if args.len() == 1 {
            o.borrow_mut().fields.insert(callee.to_string(), args[0].clone());
        }
        return Ok(ov);
    }
    match ty.as_deref() {
        Some("java.util.Random") => return Ok(Value::Unknown),
        Some("java.text.SimpleDateFormat") => {
            let pat = o.borrow().fields.get("pattern").cloned().unwrap_or(Value::Null);
            let a0 = args.first().cloned().unwrap_or(Value::Unknown);
            let Value::Str(pat) = pat else {
                return Ok(if callee == "parse" { date_value(None, false) } else { Value::Unknown });
            };
            if callee == "parse" {
                let Value::Str(s) = &a0 else { return Ok(date_value(None, false)) };
                let f = py_fmt(&pat);
                if let Some(d) = strptime(s, &f) {
                    return Ok(date_value(Some(d), false));
                }
                // SimpleDateFormat нестрогий: лишний хвост строки игнорируется
                let n = strftime(now(), &f).chars().count();
                let head: String = s.chars().take(n).collect();
                return Ok(date_value(strptime(&head, &f), false));
            }
            if callee == "format" {
                if let Value::Date(d) = &a0 {
                    if let Some(v) = d.borrow().value {
                        return Ok(Value::string(strftime(v, &py_fmt(&pat))));
                    }
                }
            }
            return Ok(Value::Unknown);
        }
        Some("java.text.DecimalFormat") => {
            let pat = o.borrow().fields.get("pattern").cloned().unwrap_or(Value::Null);
            let a0 = args.first().map(num).unwrap_or(Value::Unknown);
            if let (true, Value::Str(p), Some(x)) = (callee == "format", &pat, a0.as_num()) {
                let digits = p.split_once('.').map(|(_, d)| d.chars().count()).unwrap_or(0);
                return Ok(Value::string(format!("{:.*}", digits, x.f())));
            }
            return Ok(Value::Unknown);
        }
        Some("java.util.Iterator") => {
            let (items, i, exact) = {
                let b = o.borrow();
                let items = match b.fields.get("#items") {
                    Some(Value::List(l)) => l.borrow().items.clone(),
                    _ => return err("KeyError: #items"),
                };
                let i = b.fields.get("#i").and_then(Value::as_int).unwrap_or(0);
                let exact = matches!(b.fields.get("#exact"), Some(Value::Bool(true)));
                (items, i, exact)
            };
            return Ok(match callee {
                "hasNext" => {
                    if (i as usize) < items.len() {
                        Value::Bool(true)
                    } else if exact {
                        Value::Bool(false)
                    } else {
                        Value::Unknown
                    }
                }
                "next" => {
                    o.borrow_mut().fields.insert("#i".to_string(), Value::Int(i + 1));
                    items.get(i as usize).cloned().unwrap_or(Value::Unknown)
                }
                _ => Value::Unknown,
            });
        }
        Some("com.fasterxml.jackson.databind.ObjectMapper") => return Ok(json_call(callee, args)),
        _ => {}
    }
    let (found, val) = project_method(it, fr, &ov, callee, args)?;
    if found {
        return Ok(val);
    }
    if callee.starts_with("get") && callee.len() > 3 && args.is_empty() {
        let name = field_name(callee, "get");
        let b = o.borrow();
        if b.fields.contains_key(&name) || b.open {
            return Ok(b.get(&name));
        }
        return Ok(Value::Null);
    }
    if callee.starts_with("is") && callee.len() > 2 && args.is_empty() {
        let name = field_name(callee, "is");
        let b = o.borrow();
        if let Some(v) = b.fields.get(&name) {
            return Ok(v.clone());
        }
        let mut cs = callee.chars();
        let alt = cs.next().map(|f| f.to_lowercase().collect::<String>() + cs.as_str()).unwrap_or_default();
        if let Some(v) = b.fields.get(&alt) {
            return Ok(v.clone());
        }
        return Ok(Value::Unknown);
    }
    if callee.starts_with("set") && callee.len() > 3 && args.len() == 1 {
        it.set_field(&ov, &field_name(callee, "set"), args[0].clone());
        return Ok(Value::Null);
    }
    if callee == "equals" {
        return Ok(equals_value(&ov, args.first().unwrap_or(&Value::Unknown)).value());
    }
    if matches!(callee, "hashCode" | "toString" | "getClass") {
        return Ok(Value::Unknown);
    }
    run_unknown_lambdas(it, args, fr)?;
    Ok(Value::Unknown)
}

// --- String ---------------------------------------------------------------------------------------------------------

/// `s[a:b]` Python по символам.
fn py_slice(s: &str, a: i64, b: Option<i64>) -> String {
    let cs: Vec<char> = s.chars().collect();
    let n = cs.len() as i64;
    let norm = |i: i64| -> i64 {
        let i = if i < 0 { i + n } else { i };
        i.clamp(0, n)
    };
    let (lo, hi) = (norm(a), b.map(norm).unwrap_or(n));
    if lo >= hi {
        String::new()
    } else {
        cs[lo as usize..hi as usize].iter().collect()
    }
}

/// `re.split(pattern, s)` Python (группы включаются); `None` — шаблон не компилируется.
fn re_split(pattern: &str, s: &str) -> Option<Vec<Value>> {
    let re = Regex::new(pattern).ok()?;
    let mut out = Vec::new();
    let mut last = 0;
    for c in re.captures_iter(s) {
        let m = c.get(0).unwrap();
        out.push(Value::str(&s[last..m.start()]));
        for g in 1..c.len() {
            out.push(c.get(g).map(|x| Value::str(x.as_str())).unwrap_or(Value::Null));
        }
        last = m.end();
    }
    out.push(Value::str(&s[last..]));
    Some(out)
}

fn string_call(s: &str, callee: &str, args: &[Value]) -> Value {
    let a0 = args.first().cloned().unwrap_or(Value::Unknown);
    if matches!(callee, "toString" | "trim" | "intern") && args.is_empty() {
        return Value::str(if callee == "trim" { s.trim() } else { s });
    }
    match callee {
        "length" => return Value::Int(s.chars().count() as i64),
        "isEmpty" => return Value::Bool(s.is_empty()),
        "equals" | "contentEquals" => {
            return match &a0 {
                Value::Str(x) => Value::Bool(s == &**x),
                Value::Null => Value::Bool(false),
                _ => Value::Unknown,
            };
        }
        "equalsIgnoreCase" => {
            return match &a0 {
                Value::Str(x) => Value::Bool(s.to_lowercase() == x.to_lowercase()),
                Value::Null => Value::Bool(false),
                _ => Value::Unknown,
            };
        }
        _ => {}
    }
    let a0_ok = matches!(a0, Value::Str(_) | Value::Int(_) | Value::Bool(_));
    if !a0_ok
        && !matches!(callee, "toLowerCase" | "toUpperCase" | "split" | "hashCode")
        && matches!(callee, "startsWith" | "endsWith" | "contains" | "indexOf" | "charAt" | "substring" | "concat" | "compareTo" | "replace" | "matches")
    {
        return Value::Unknown;
    }
    let a0s = a0.as_str();
    match callee {
        "startsWith" if a0s.is_some() => Value::Bool(s.starts_with(a0s.unwrap())),
        "endsWith" if a0s.is_some() => Value::Bool(s.ends_with(a0s.unwrap())),
        "contains" if a0s.is_some() => Value::Bool(s.contains(a0s.unwrap())),
        "indexOf" if a0s.is_some() => Value::Int(match s.find(a0s.unwrap()) {
            Some(b) => s[..b].chars().count() as i64,
            None => -1,
        }),
        "charAt" if a0.as_int_or_bool().is_some() => {
            let i = a0.as_int_or_bool().unwrap();
            if i >= 0 {
                s.chars().nth(i as usize).map(|c| Value::string(c.to_string())).unwrap_or(Value::Unknown)
            } else {
                Value::Unknown
            }
        }
        "substring" if a0.as_int_or_bool().is_some() => {
            let a1 = args.get(1);
            match a1 {
                None | Some(Value::Null) => Value::string(py_slice(s, a0.as_int_or_bool().unwrap(), None)),
                Some(x) if x.as_int_or_bool().is_some() => Value::string(py_slice(s, a0.as_int_or_bool().unwrap(), x.as_int_or_bool())),
                _ => Value::Unknown,
            }
        }
        "toLowerCase" => Value::string(s.to_lowercase()),
        "toUpperCase" => Value::string(s.to_uppercase()),
        "split" if a0s.is_some() => {
            let p = a0s.unwrap();
            let parts = re_split(p, s).unwrap_or_else(|| s.split(p).map(Value::str).collect());
            Value::list(parts, true)
        }
        "concat" if a0s.is_some() => Value::string(format!("{s}{}", a0s.unwrap())),
        "replace" if a0s.is_some() && matches!(args.get(1), Some(Value::Str(_))) => {
            Value::string(s.replace(a0s.unwrap(), args[1].as_str().unwrap()))
        }
        "compareTo" if a0s.is_some() => {
            let o = a0s.unwrap();
            Value::Int((s > o) as i64 - (s < o) as i64)
        }
        _ => Value::Unknown,
    }
}

// --- числа ----------------------------------------------------------------------------------------------------------

fn as_num_nb(v: &Value) -> Option<Num> {
    match v {
        Value::Bool(b) => Some(Num::Int(*b as i64)),
        other => other.as_num(),
    }
}

fn py_round(n: Num, nd: i64) -> Num {
    match n {
        Num::Float(f) => Num::Float(round_digits(f, nd)),
        Num::Int(i) => {
            if nd >= 0 {
                Num::Int(i)
            } else {
                let p = 10_i64.pow((-nd).min(18) as u32);
                let r = round_half_even(i as f64 / p as f64);
                Num::Int(r * p)
            }
        }
    }
}

fn number_call(recv: &Value, callee: &str, args: &[Value]) -> Value {
    let n = as_num_nb(recv).unwrap();
    let a0 = args.first().map(num).unwrap_or(Value::Unknown);
    match callee {
        "intValue" | "longValue" => {
            return Value::Int(match n {
                Num::Int(i) => i,
                Num::Float(f) => f as i64,
            })
        }
        "doubleValue" | "floatValue" => return Value::Float(n.f()),
        "toString" => return to_jstr(recv),
        _ => {}
    }
    let a = a0.as_num();
    if callee == "compareTo" {
        if let Some(a) = a {
            return Value::Int(a.lt(n) as i64 - n.lt(a) as i64);
        }
    }
    if callee == "equals" {
        return match a {
            Some(a) => Value::Bool(n.eq(a)),
            None => Value::Unknown,
        };
    }
    let Some(a) = a else { return Value::Unknown };
    let arith = |fi: fn(i64, i64) -> i64, ff: fn(f64, f64) -> f64| match (n, a) {
        (Num::Int(x), Num::Int(y)) => Value::Int(fi(x, y)),
        _ => Value::Float(ff(n.f(), a.f())),
    };
    match callee {
        "add" => arith(i64::wrapping_add, |x, y| x + y),
        "subtract" => arith(i64::wrapping_sub, |x, y| x - y),
        "multiply" => arith(i64::wrapping_mul, |x, y| x * y),
        "divide" => {
            if a.eq(Num::Int(0)) {
                Value::Unknown
            } else {
                Value::Float(n.f() / a.f())
            }
        }
        "setScale" => {
            let nd = match a {
                Num::Int(i) => i,
                Num::Float(f) => f as i64,
            };
            py_round(n, nd).value()
        }
        "max" => {
            if n.lt(a) { a.value() } else { n.value() }
        }
        "min" => {
            if a.lt(n) { a.value() } else { n.value() }
        }
        _ => Value::Unknown,
    }
}

// --- Optional -------------------------------------------------------------------------------------------------------

fn optional_call(it: &mut Interpreter, fr: &mut Frame, o: &Shared<OptionalV>, callee: &str, args: &[Value]) -> R<Value> {
    let (v, maybe) = {
        let b = o.borrow();
        (b.value.clone(), b.maybe)
    };
    let ov = Value::Optional(o.clone());
    match callee {
        "isPresent" => return Ok(if v.is_unknown() || maybe { Value::Unknown } else { Value::Bool(!v.is_null()) }),
        "isEmpty" => return Ok(if v.is_unknown() || maybe { Value::Unknown } else { Value::Bool(v.is_null()) }),
        _ => {}
    }
    if maybe && matches!(callee, "orElse" | "orElseGet" | "orElseThrow") {
        if callee == "orElseGet" {
            if let Some(a) = args.first() {
                run(it, a, &[], fr)?;
            }
        }
        return Ok(if callee == "orElse" { Value::Unknown } else { v });
    }
    match callee {
        "get" => Ok(if v.is_null() { Value::Unknown } else { v }),
        "orElse" => {
            if v.is_unknown() {
                return Ok(Value::Unknown);
            }
            Ok(if !v.is_null() { v } else { args.first().cloned().unwrap_or(Value::Null) })
        }
        "orElseGet" | "orElseThrow" => {
            if v.is_null() {
                let r = match args.first() {
                    Some(a) => run(it, a, &[], fr)?,
                    None => Value::Unknown,
                };
                return Ok(if callee == "orElseGet" { r } else { Value::Unknown });
            }
            Ok(v)
        }
        "ifPresent" => {
            if !v.is_null() {
                if let Some(a) = args.first() {
                    run(it, a, &[v], fr)?;
                }
            }
            Ok(Value::Null)
        }
        "map" => {
            if v.is_null() {
                return Ok(ov);
            }
            let r = match args.first() {
                Some(a) => run(it, a, &[v], fr)?,
                None => Value::Unknown,
            };
            Ok(Value::optional(r, false))
        }
        _ => Ok(Value::Unknown),
    }
}

// --- List -----------------------------------------------------------------------------------------------------------

/// Индекс первого равного элемента и уверенность (`false` — равенство с частью элементов неизвестно).
fn find(lst: &ListV, v: &Value) -> (i64, bool) {
    let mut sure = lst.exact;
    for (i, x) in lst.items.iter().enumerate() {
        match equals_value(x, v) {
            Tri::True => return (i as i64, sure),
            Tri::Unknown => sure = false,
            Tri::False => {}
        }
    }
    (-1, sure)
}

fn add(lst: &Shared<ListV>, v: Value) -> bool {
    let mut b = lst.borrow_mut();
    if b.is_set {
        let (idx, sure) = find(&b, &v);
        if idx >= 0 {
            return false;
        }
        if !sure && v.is_unknown() {
            b.exact = false;
        }
    }
    b.items.push(v);
    true
}

/// `list.contains(x)` вызывает `x.equals(элемент)`: проектный `equals` исполняется (без ребра calls).
fn element_equals(it: &mut Interpreter, fr: &mut Frame, lst: &Shared<ListV>, probe: &Value) -> R<()> {
    let first = lst.borrow().items.first().cloned();
    let (Some(first), Value::Obj(o)) = (first, probe) else { return Ok(()) };
    let ty = o.borrow().ty.clone();
    let Some(ty) = ty.filter(|t| !t.is_empty()) else { return Ok(()) };
    let tid = it.types.resolve(Some(&ty), Some(&fr.module));
    let eq = it.types.method_of(tid.as_deref(), "equals", Some(1));
    if let Some(eq) = eq.filter(|e| it.ir.contains_key(e) && it.flags.element_callbacks) {
        let w = why("STATE", "ELEMENT_CALLBACK:contains(m4)");
        it.sink.execute(&eq, &w, Some(format!("library|{}|contains", fr.method)));
        let unit = fr.unit.clone();
        it.invoke(&eq, probe, &[first], &unit, &w)?;
    }
    Ok(())
}

fn list_call(it: &mut Interpreter, fr: &mut Frame, lst: &Shared<ListV>, callee: &str, args: &[Value]) -> R<Value> {
    let a0 = args.first().cloned().unwrap_or(Value::Unknown);
    let (len, exact) = {
        let b = lst.borrow();
        (b.items.len(), b.exact)
    };
    match callee {
        "size" => return Ok(if exact { Value::Int(len as i64) } else { Value::Unknown }),
        "isEmpty" => return Ok(if exact { Value::Bool(len == 0) } else { Value::Unknown }),
        "add" | "addAll" | "clear" | "remove" | "set" => it.touch_list(lst),
        _ => {}
    }
    match callee {
        "add" => {
            if args.len() == 1 {
                return Ok(Value::Bool(add(lst, a0)));
            }
            let item = args.get(1).cloned().unwrap_or(Value::Unknown);
            let mut b = lst.borrow_mut();
            let n = b.items.len() as i64;
            let pos = match a0.as_int_or_bool() {
                Some(i) => (if i < 0 { i + n } else { i }).clamp(0, n),
                None => n,
            };
            b.items.insert(pos as usize, item);
            if a0.as_int_or_bool().is_none() {
                b.exact = false;
            }
            Ok(Value::Bool(true))
        }
        "addAll" => {
            if let Value::List(src) = &a0 {
                let (items, ex) = {
                    let s = src.borrow();
                    (s.items.clone(), s.exact)
                };
                for x in items {
                    add(lst, x);
                }
                let mut b = lst.borrow_mut();
                b.exact = b.exact && ex;
            } else {
                lst.borrow_mut().exact = false;
            }
            Ok(Value::Bool(true))
        }
        "get" => {
            if let Some(i) = a0.as_int_or_bool() {
                let b = lst.borrow();
                if i >= 0 && (i as usize) < b.items.len() {
                    return Ok(b.items[i as usize].clone());
                }
            }
            Ok(Value::Unknown)
        }
        "contains" | "indexOf" | "remove" => {
            element_equals(it, fr, lst, &a0)?;
            if callee == "remove" && matches!(a0, Value::Int(_)) && !lst.borrow().is_set {
                let i = a0.as_int().unwrap();
                let mut b = lst.borrow_mut();
                if b.exact && i >= 0 && (i as usize) < b.items.len() {
                    return Ok(b.items.remove(i as usize));
                }
                b.exact = false;
                return Ok(Value::Unknown);
            }
            let (idx, sure) = find(&lst.borrow(), &a0);
            let ex = lst.borrow().exact;
            match callee {
                "contains" => Ok(if idx >= 0 && ex { Value::Bool(true) } else if sure { Value::Bool(false) } else { Value::Unknown }),
                "indexOf" => Ok(if idx >= 0 && sure { Value::Int(idx) } else if sure { Value::Int(-1) } else { Value::Unknown }),
                _ => {
                    if idx >= 0 {
                        let mut b = lst.borrow_mut();
                        b.items.remove(idx as usize);
                        if !sure {
                            b.exact = false;
                        }
                        return Ok(Value::Bool(true));
                    }
                    if !sure {
                        lst.borrow_mut().exact = false;
                        return Ok(Value::Unknown);
                    }
                    Ok(Value::Bool(false))
                }
            }
        }
        "removeAll" | "retainAll" => {
            it.touch_list(lst);
            let Value::List(other) = &a0 else {
                lst.borrow_mut().exact = false;
                return Ok(Value::Unknown);
            };
            let items = lst.borrow().items.clone();
            let mut keep = Vec::new();
            let mut exact_now = lst.borrow().exact;
            for x in items {
                let (idx, sure) = find(&other.borrow(), &x);
                let hit = idx >= 0;
                if (callee == "removeAll") != hit {
                    keep.push(x);
                }
                if !sure {
                    exact_now = false;
                }
            }
            let mut b = lst.borrow_mut();
            b.items = keep;
            b.exact = exact_now && other.borrow().exact;
            Ok(Value::Bool(true))
        }
        "containsAll" if matches!(a0, Value::List(_)) => {
            let Value::List(other) = &a0 else { unreachable!() };
            let mut res = Tri::True;
            let items = other.borrow().items.clone();
            for x in &items {
                let (idx, sure) = find(&lst.borrow(), x);
                if idx < 0 {
                    if sure {
                        return Ok(Value::Bool(false));
                    }
                    res = Tri::Unknown;
                }
            }
            Ok(if other.borrow().exact { res.value() } else { Value::Unknown })
        }
        "iterator" | "listIterator" => {
            let b = lst.borrow();
            let fields: IndexMap<String, Value> = [
                ("#items".to_string(), Value::list(b.items.clone(), true)),
                ("#i".to_string(), Value::Int(0)),
                ("#exact".to_string(), Value::Bool(b.exact)),
            ]
            .into_iter()
            .collect();
            Ok(Value::obj(Some("java.util.Iterator"), fields, false))
        }
        "stream" | "parallelStream" | "toArray" | "sorted" | "distinct" => {
            if callee == "sorted" && !args.is_empty() {
                let first = lst.borrow().items.first().cloned().unwrap_or(Value::Unknown);
                run(it, &a0, &[first.clone(), first], fr)?;
            }
            let b = lst.borrow();
            let mut n = ListV::new(b.items.clone(), b.exact);
            n.elem_type = b.elem_type.clone();
            Ok(Value::List(shared(n)))
        }
        "sort" => {
            let (first, last) = {
                let b = lst.borrow();
                (b.items.first().cloned(), b.items.last().cloned())
            };
            if let (false, Some(f), Some(l)) = (args.is_empty(), first, last) {
                run(it, &a0, &[f, l], fr)?;
            }
            Ok(Value::Null)
        }
        "filter" => {
            let items = lst.borrow().items.clone();
            let mut out = Vec::new();
            let mut ex = exact;
            for x in &items {
                match tri(&run(it, &a0, &[x.clone()], fr)?) {
                    Tri::True => out.push(x.clone()),
                    Tri::Unknown => {
                        out.push(x.clone());
                        ex = false;
                    }
                    Tri::False => {}
                }
            }
            if items.is_empty() && !exact {
                run(it, &a0, &[Value::Unknown], fr)?;
            }
            Ok(Value::list(out, ex))
        }
        "map" => {
            let items = lst.borrow().items.clone();
            let mut out = Vec::new();
            for x in &items {
                out.push(run(it, &a0, &[x.clone()], fr)?);
            }
            if items.is_empty() && !exact {
                run(it, &a0, &[Value::Unknown], fr)?;
            }
            Ok(Value::list(out, exact))
        }
        "forEach" => {
            let items = lst.borrow().items.clone();
            let items = if items.is_empty() && !exact { vec![Value::Unknown] } else { items };
            for x in items {
                run(it, &a0, &[x], fr)?;
            }
            Ok(Value::Null)
        }
        "collect" | "toList" => Ok(Value::list(lst.borrow().items.clone(), exact)),
        "count" => Ok(if exact { Value::Int(len as i64) } else { Value::Unknown }),
        "findFirst" | "findAny" => {
            let first = lst.borrow().items.first().cloned();
            Ok(match first {
                Some(f) => Value::optional(if exact { f } else { Value::Unknown }, false),
                None => Value::optional(if exact { Value::Null } else { Value::Unknown }, false),
            })
        }
        "anyMatch" | "allMatch" | "noneMatch" => {
            let items = lst.borrow().items.clone();
            let mut rs = Vec::new();
            for x in &items {
                rs.push(tri(&run(it, &a0, &[x.clone()], fr)?));
            }
            let has_unknown = rs.contains(&Tri::Unknown);
            Ok(match callee {
                "anyMatch" => {
                    if rs.contains(&Tri::True) {
                        Value::Bool(true)
                    } else if exact && !has_unknown {
                        Value::Bool(false)
                    } else {
                        Value::Unknown
                    }
                }
                "allMatch" => {
                    if rs.contains(&Tri::False) {
                        Value::Bool(false)
                    } else if exact && !has_unknown {
                        Value::Bool(true)
                    } else {
                        Value::Unknown
                    }
                }
                _ => {
                    if rs.contains(&Tri::True) {
                        Value::Bool(false)
                    } else if exact && !has_unknown {
                        Value::Bool(true)
                    } else {
                        Value::Unknown
                    }
                }
            })
        }
        "hasNext" | "next" => Ok(Value::Unknown),
        "clear" => {
            let mut b = lst.borrow_mut();
            b.items.clear();
            b.exact = true;
            Ok(Value::Null)
        }
        "set" => Ok(Value::Unknown),
        _ => {
            run_unknown_lambdas(it, args, fr)?;
            Ok(Value::Unknown)
        }
    }
}

// --- Map ------------------------------------------------------------------------------------------------------------

fn map_call(m: &Shared<MapV>, callee: &str, args: &[Value]) -> Value {
    let a0 = args.first().cloned().unwrap_or(Value::Unknown);
    let hashable = matches!(a0, Value::Str(_) | Value::Int(_) | Value::Float(_) | Value::Bool(_) | Value::Null);
    match callee {
        "put" => {
            if hashable {
                m.borrow_mut().put(a0, args.get(1).cloned().unwrap_or(Value::Unknown));
            } else {
                m.borrow_mut().exact = false;
            }
            Value::Null
        }
        "get" | "getOrDefault" => {
            if hashable {
                if let Some(v) = m.borrow().get(&a0) {
                    return v;
                }
            }
            if m.borrow().exact && hashable {
                return if callee == "getOrDefault" && args.len() > 1 { args[1].clone() } else { Value::Null };
            }
            Value::Unknown
        }
        "containsKey" => {
            if hashable && m.borrow().get(&a0).is_some() {
                return Value::Bool(true);
            }
            if m.borrow().exact && hashable { Value::Bool(false) } else { Value::Unknown }
        }
        "keySet" => {
            let b = m.borrow();
            let mut l = ListV::new(b.data.values().map(|(k, _)| k.clone()).collect(), b.exact);
            l.is_set = true;
            Value::List(shared(l))
        }
        "values" => {
            let b = m.borrow();
            Value::list(b.data.values().map(|(_, v)| v.clone()).collect(), b.exact)
        }
        "size" => {
            let b = m.borrow();
            if b.exact { Value::Int(b.data.len() as i64) } else { Value::Unknown }
        }
        "isEmpty" => {
            let b = m.borrow();
            if b.exact {
                Value::Bool(b.data.is_empty())
            } else if !b.data.is_empty() {
                Value::Bool(false)
            } else {
                Value::Unknown
            }
        }
        "entrySet" => {
            let b = m.borrow();
            let items = b
                .data
                .values()
                .map(|(k, v)| {
                    let f: IndexMap<String, Value> = [("key".to_string(), k.clone()), ("value".to_string(), v.clone())].into_iter().collect();
                    Value::obj(Some("java.util.Map$Entry"), f, false)
                })
                .collect();
            Value::list(items, b.exact)
        }
        _ => Value::Unknown,
    }
}

// --- статические вызовы ---------------------------------------------------------------------------------------------

fn static_call(it: &mut Interpreter, fr: &mut Frame, fqn: &str, callee: &str, args: &[Value]) -> R<Value> {
    let simple = fqn.rsplit('.').next().unwrap_or("");
    let a0 = args.first().cloned().unwrap_or(Value::Unknown);
    if matches!(simple, "JSON" | "JSONObject" | "JSONArray") && (JSON_WRITE.contains(&callee) || JSON_READ.contains(&callee)) {
        return Ok(json_call(callee, args));
    }
    let tid = it.types.resolve(Some(fqn), Some(&fr.module));
    if let Some(t) = tid.as_deref() {
        if callee == "builder" && args.is_empty() {
            let f: IndexMap<String, Value> = [("#builder".to_string(), Value::Bool(true))].into_iter().collect();
            return Ok(Value::obj(Some(fqn), f, false));
        }
        if it.types.is_enum(Some(t)) {
            if callee == "values" {
                let names: Vec<String> = it.types.enum_constants(t).iter().map(|(c, _)| c.clone()).collect();
                let mut items = Vec::new();
                for c in names {
                    items.push(it.enum_const(t, &c)?);
                }
                return Ok(Value::list(items, true));
            }
            if let (true, Value::Str(s)) = (callee == "valueOf", &a0) {
                return it.enum_const(t, s);
            }
            return Ok(Value::Unknown);
        }
    }
    if simple == "Calendar" && callee == "getInstance" {
        return Ok(date_value(Some(now()), true));
    }
    if simple == "UUID" && callee == "randomUUID" {
        return Ok(Value::string(fresh_uuid()));
    }
    if simple == "UUID" && matches!(callee, "fromString" | "nameUUIDFromBytes") {
        return Ok(if matches!(a0, Value::Str(_)) && callee == "fromString" { a0 } else { Value::Unknown });
    }
    if simple == "String" && callee == "valueOf" {
        return Ok(to_jstr(&a0));
    }
    if simple == "String" && callee == "format" {
        return Ok(Value::Unknown);
    }
    if matches!(simple, "Integer" | "Long") && matches!(callee, "parseInt" | "valueOf" | "parseLong") {
        return Ok(match num(&a0).as_num() {
            Some(Num::Int(i)) => Value::Int(i),
            Some(Num::Float(f)) => Value::Int(f as i64),
            None => Value::Unknown,
        });
    }
    if matches!(simple, "Double" | "Float") && matches!(callee, "parseDouble" | "valueOf" | "parseFloat") {
        return Ok(match num(&a0).as_num() {
            Some(n) => Value::Float(n.f()),
            None => Value::Unknown,
        });
    }
    if simple == "Math" {
        let ns: Vec<Value> = args.iter().map(num).collect();
        if ns.iter().any(Value::is_unknown) {
            return Ok(Value::Unknown);
        }
        let nums: Vec<Num> = ns.iter().filter_map(Value::as_num).collect();
        return match callee {
            "abs" => match nums.as_slice() {
                [Num::Int(i)] => Ok(Value::Int(i.wrapping_abs())),
                [Num::Float(f)] => Ok(Value::Float(f.abs())),
                _ => err("TypeError: abs"),
            },
            "max" | "min" if nums.len() >= 2 => {
                let mut best = nums[0];
                for &x in &nums[1..] {
                    if (callee == "max" && best.lt(x)) || (callee == "min" && x.lt(best)) {
                        best = x;
                    }
                }
                Ok(best.value())
            }
            "max" | "min" => err("TypeError: max/min"),
            "round" => match nums.as_slice() {
                [Num::Int(i)] => Ok(Value::Int(*i)),
                [Num::Float(f)] => Ok(Value::Int(round_half_even(*f))),
                [n, Num::Int(nd)] => Ok(py_round(*n, *nd).value()),
                _ => err("TypeError: round"),
            },
            _ => Ok(Value::Unknown),
        };
    }
    if simple == "Optional" {
        match callee {
            "of" | "ofNullable" => return Ok(Value::optional(a0, false)),
            "empty" => return Ok(Value::optional(Value::Null, false)),
            _ => {}
        }
    }
    if matches!(simple, "Arrays" | "List" | "Set" | "Collections" | "Stream")
        && matches!(callee, "asList" | "of" | "singletonList" | "emptyList" | "stream")
    {
        if matches!(callee, "stream" | "asList") && args.len() == 1 {
            if let Value::List(l) = &a0 {
                let b = l.borrow();
                let mut n = ListV::new(b.items.clone(), b.exact);
                n.elem_type = b.elem_type.clone();
                return Ok(Value::List(shared(n)));
            }
        }
        if args.iter().any(Value::is_unknown) && callee == "asList" && args.len() == 1 {
            return Ok(Value::list(Vec::new(), false));
        }
        return Ok(Value::list(args.to_vec(), true));
    }
    if simple == "Collections" && callee == "sort" {
        return Ok(Value::Null);
    }
    if simple == "Objects" {
        match callee {
            "isNull" | "nonNull" => {
                if a0.is_unknown() {
                    return Ok(Value::Unknown);
                }
                return Ok(Value::Bool(if callee == "isNull" { a0.is_null() } else { !a0.is_null() }));
            }
            "equals" if args.len() == 2 => return Ok(equals_value(&args[0], &args[1]).value()),
            "requireNonNull" => return Ok(a0),
            _ => {}
        }
    }
    if simple == "StringUtils" && matches!(callee, "isEmpty" | "hasText" | "hasLength" | "isBlank" | "isNotEmpty") {
        if a0.is_unknown() || matches!(a0, Value::Concat(_)) {
            return Ok(Value::Unknown);
        }
        let empty = a0.is_null()
            || match &a0 {
                Value::Str(s) => {
                    if matches!(callee, "isEmpty" | "hasLength" | "isNotEmpty") { s.is_empty() } else { s.trim().is_empty() }
                }
                _ => false,
            };
        return Ok(Value::Bool(if matches!(callee, "isEmpty" | "isBlank") { empty } else { !empty }));
    }
    if simple == "ResponseEntity" && callee == "ok" {
        return Ok(Value::wrapper(if args.is_empty() { Value::Null } else { a0 }, "response"));
    }
    if simple == "System" && callee == "currentTimeMillis" {
        return Ok(Value::Unknown);
    }
    run_unknown_lambdas(it, args, fr)?;
    Ok(Value::Unknown)
}

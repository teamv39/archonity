//! Доступ к полям JSON-объектов в духе `dict.get` Python: узлы скелета и IR читаются как `serde_json::Value`.

use serde_json::Value as Json;

pub fn get<'a>(v: &'a Json, key: &str) -> Option<&'a Json> {
    v.as_object().and_then(|o| o.get(key))
}

pub fn str_<'a>(v: &'a Json, key: &str) -> Option<&'a str> {
    get(v, key).and_then(Json::as_str)
}

pub fn int(v: &Json, key: &str) -> Option<i64> {
    get(v, key).and_then(Json::as_i64)
}

pub fn arr<'a>(v: &'a Json, key: &str) -> &'a [Json] {
    get(v, key).and_then(Json::as_array).map(Vec::as_slice).unwrap_or(&[])
}

/// Строки массива-поля; не строки пропускаются.
pub fn strs<'a>(v: &'a Json, key: &str) -> Vec<&'a str> {
    arr(v, key).iter().filter_map(Json::as_str).collect()
}

/// `str(x)` Python для значений контекста: строки как есть, остальное — JSON.
pub fn py_str(v: &Json) -> String {
    match v {
        Json::String(s) => s.clone(),
        Json::Null => "None".to_string(),
        Json::Bool(b) => if *b { "True" } else { "False" }.to_string(),
        other => other.to_string(),
    }
}

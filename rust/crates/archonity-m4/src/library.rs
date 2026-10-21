//! Библиотека Java: коллекции, строки, Optional, Stream, даты, Jackson, Lombok (`engine/executor/library.py`).

use archonity_model::values::Value;

/// Вызов метода библиотеки на получателе; `None` — метод не из библиотеки.
pub fn call_library(_receiver: &Value, _name: &str, _args: &[Value]) -> Option<Value> {
    todo!("D2")
}

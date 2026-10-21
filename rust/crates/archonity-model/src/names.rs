//! Имена: простое имя класса и `camel_to_snake` (`engine/manifest.py`, `engine/executor/schema.py`).

/// Простое имя класса без пакетов и вложенных классов; по умолчанию в нижнем регистре.
pub fn simple_name(_fqn: Option<&str>, _lower: bool) -> String {
    todo!("этап 1: engine/manifest.py::simple_name")
}

/// `fooBar` -> `foo_bar`.
pub fn camel_to_snake(_name: &str) -> String {
    todo!("этап 1: engine/manifest.py::camel_to_snake")
}

//! Интерпретатор IR (`engine/executor/interpreter.py`): условия в трёхзначной логике, вызовы, события исполнения.
//!
//! Этап 0: только форма публичного API. Внутреннее устройство (Frame, Sink, обход выражений) задаёт D2.

use std::collections::BTreeSet;

use archonity_model::values::Value;
use archonity_model::RuleFlags;

/// Что исполнилось в шаге: методы, рёбра с причинами, отсевы, решения по UNKNOWN.
#[derive(Debug, Default)]
pub struct Sink {
    /// Метод -> (тип источника, правило, через что).
    pub methods: indexmap::IndexMap<String, (String, String, String)>,
    pub calls: indexmap::IndexMap<(String, String), (String, String)>,
    pub remote: indexmap::IndexMap<(String, String), (String, String)>,
    pub data: indexmap::IndexMap<(String, String), (String, String)>,
    /// `(relation, source, target, source_type, rule)`.
    pub prunes: Vec<(String, String, String, String, String)>,
    /// Решения по условиям UNKNOWN (`m4_unknowns.json`).
    pub unknowns: Vec<serde_json::Value>,
}

pub struct Interpreter {
    pub flags: RuleFlags,
    pub invocations: u64,
}

impl Interpreter {
    /// Исполняет обработчик с аргументами; возвращает события и результат.
    pub fn run_handler(&mut self, _handler: &str, _args: Vec<Value>, _expected: &str, _step: Option<i64>) -> (Sink, Value) {
        todo!("D2")
    }

    /// Методы, которых нет в IR: исполняется только то, что есть в `ir`.
    pub fn known_methods(&self) -> BTreeSet<String> {
        todo!("D2")
    }
}

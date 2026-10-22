//! Рёбра шага: выход `StepExecutor::run_step` (множества, как в Python).

use std::collections::BTreeSet;

/// Рёбра одного шага до правила Spring Security и проекции M5. Порядок не значим: в ответе рёбра сортируются.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StepEdges {
    /// Исполненные методы (`executes`).
    pub methods: BTreeSet<String>,
    /// `(источник, цель)`.
    pub calls: BTreeSet<(String, String)>,
    pub remote: BTreeSet<(String, String)>,
    pub data: BTreeSet<(String, String)>,
}

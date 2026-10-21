//! M5, R7 (`engine/projection.py::project_constructors`): конструктор в ответе, только если из него исполнился вызов проекта.

use std::collections::BTreeSet;

use archonity_io::DecisionLedger;
use archonity_model::flags::Constructors;

pub fn project_constructors(
    _methods: &mut BTreeSet<String>,
    _calls: &mut BTreeSet<(String, String)>,
    _remote: &mut BTreeSet<(String, String)>,
    _data: &mut BTreeSet<(String, String)>,
    _mode: Constructors,
    _ledger: &mut DecisionLedger,
) {
    todo!("P3")
}

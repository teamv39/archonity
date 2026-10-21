//! Правило Spring Security при входе (`engine/spring_security.py::apply_spring_security`).

use std::collections::BTreeSet;

use archonity_io::{DecisionLedger, SkeletonIndex};

pub fn apply_spring_security(
    _index: &SkeletonIndex,
    _methods: &mut BTreeSet<String>,
    _calls: &mut BTreeSet<(String, String)>,
    _data: &mut BTreeSet<(String, String)>,
    _ledger: &mut DecisionLedger,
) {
    todo!("P3")
}

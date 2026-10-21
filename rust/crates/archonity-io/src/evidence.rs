//! `evidence.json` v2 (`engine/evidence.py`): запись на каждое ребро ответа.

use std::path::Path;

use anyhow::Result;
use serde_json::Value as Json;

use crate::decisions::DecisionLedger;
use crate::skeleton::SkeletonIndex;

pub struct EvidenceLogger<'a> {
    pub index: &'a SkeletonIndex,
}

impl<'a> EvidenceLogger<'a> {
    pub fn new(index: &'a SkeletonIndex, _targets_root: &Path) -> EvidenceLogger<'a> {
        EvidenceLogger { index }
    }

    pub fn build(&self, _ledger: &DecisionLedger) -> Json {
        todo!("P2")
    }

    pub fn save(&self, _ledger: &DecisionLedger, _path: &Path) -> Result<()> {
        todo!("P2")
    }
}

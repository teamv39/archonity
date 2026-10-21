//! Загрузка IR тел методов: `data/ir/<module>.json` (`{"methods": {id: {params, body}}}`).

use std::path::Path;

use anyhow::Result;
use indexmap::IndexMap;
use serde_json::Value as Json;

/// Тела методов по ID метода скелета.
pub type IrStore = IndexMap<String, Json>;

pub fn load_ir_dir(_dir: &Path) -> Result<IrStore> {
    todo!("D1")
}

//! Загрузка IR тел методов: `data/ir/<module>.json` (`{"methods": {id: {params, body, …}}}`).

use std::path::Path;
use std::rc::Rc;

use anyhow::{Context, Result};
use indexmap::IndexMap;
use serde_json::Value as Json;

/// Тела методов по ID метода скелета. Поздние файлы перекрывают ранние, позиция ключа остаётся первой.
pub type IrStore = IndexMap<String, Rc<Json>>;

pub fn load_ir_dir(dir: &Path) -> Result<IrStore> {
    let mut paths: Vec<_> = std::fs::read_dir(dir)
        .with_context(|| format!("не прочитан каталог IR {}", dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .collect();
    paths.sort();
    let mut ir = IrStore::new();
    for p in paths {
        let text = std::fs::read(&p).with_context(|| format!("не прочитан {}", p.display()))?;
        let doc: Json = serde_json::from_slice(&text).with_context(|| format!("разбор {}", p.display()))?;
        if let Some(ms) = doc.get("methods").and_then(Json::as_object) {
            for (k, v) in ms {
                ir.insert(k.clone(), Rc::new(v.clone()));
            }
        }
    }
    Ok(ir)
}

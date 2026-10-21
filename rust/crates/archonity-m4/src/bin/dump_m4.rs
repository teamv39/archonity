//! Срезы M4 в формате `scripts/rust_oracles.py slices` (`m4_slices.json`, ключи отсортированы) для сверки с Python:
//! `dump-m4 <скелет.json.gz> <entity_ir.json> <каталог IR> <исходники проекта> <выход>`.

use std::path::Path;

use archonity_io::json_py::{dumps_indent1, sort_keys};
use archonity_io::SkeletonIndex;
use archonity_m4::envelope::derive;
use archonity_m4::ir::load_ir_dir;
use archonity_m4::manifest::entity_kinds;
use archonity_m4::schema::EntitySchema;
use serde_json::{json, Value as Json};

fn main() -> anyhow::Result<()> {
    let a: Vec<String> = std::env::args().collect();
    let ix = SkeletonIndex::load(Path::new(&a[1]), None, Path::new(&a[2]))?;
    let ir = load_ir_dir(Path::new(&a[3]))?;
    let env = derive(&ix, &ir, Some(Path::new(&a[4])));
    let kinds: serde_json::Map<String, Json> = entity_kinds(&ix)
        .into_iter()
        .map(|(k, v)| (k, json!({"kind": v.kind, "types": v.types, "id_fields": v.id_fields, "tables": v.tables})))
        .collect();
    let schema = EntitySchema::new(Some(&ix));
    let mut known: Vec<&String> = schema.known_kinds();
    known.sort();
    let mut methods: Vec<&String> = ir.keys().collect();
    methods.sort();
    let data = json!({
        "envelope": env.map(|e| json!({"name": e.name, "status": e.status, "success": e.success, "data": e.data})),
        "kinds": kinds,
        "ir_methods": methods,
        "known_kinds": known,
    });
    std::fs::write(&a[5], dumps_indent1(&sort_keys(&data)) + "\n")?;
    Ok(())
}

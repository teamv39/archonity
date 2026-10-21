//! Срезы загрузчиков в формате `scripts/rust_oracles.py slices` (ключи отсортированы) для сверки с Python:
//! `dump-slices <скелет.json.gz> <entity_ir.json> <выход>`.

use std::collections::BTreeSet;
use std::path::Path;

use archonity_io::entities::{Entity, RepositoryCall};
use archonity_io::json_py::{dumps_indent1, sort_keys};
use archonity_io::SkeletonIndex;
use serde_json::{json, Value as Json};

fn sets<'a>(m: impl Iterator<Item = (&'a String, &'a BTreeSet<String>)>) -> Json {
    Json::Object(m.map(|(k, v)| (k.clone(), json!(v.iter().collect::<Vec<_>>()))).collect())
}

fn entity(e: &Entity) -> Json {
    json!({
        "type": e.ty, "module": e.module, "table": e.table, "id_field": e.id_field, "no_arg_ctor": e.no_arg_ctor,
        "ctor_statements": e.ctor_statements, "embedded": e.embedded,
        "collections": e.collections.iter().map(|(k, (f, t))| (k.clone(), json!([f, t]))).collect::<serde_json::Map<_, _>>(),
    })
}

fn call(c: &RepositoryCall) -> Json {
    json!({
        "method": c.method, "line": c.line, "col": c.col, "callee": c.callee, "operation": c.operation,
        "expects": c.expects, "expects_reason": c.expects_reason, "id_assigned": c.id_assigned,
        "id_assigned_reason": c.id_assigned_reason, "entity": c.entity.as_ref().map(entity),
        "tables": c.tables.iter().collect::<Vec<_>>(), "main_table": c.main_table, "ctors": c.ctors,
        "lazy_tables": c.lazy_tables, "collections_loaded": c.collections_loaded,
        "collections_loaded_reason": c.collections_loaded_reason,
        "element_callbacks": c.element_callbacks.iter().map(|(a, b)| json!([a, b])).collect::<Vec<_>>(),
    })
}

fn main() -> anyhow::Result<()> {
    let a: Vec<String> = std::env::args().collect();
    let ix = SkeletonIndex::load(Path::new(&a[1]), None, Path::new(&a[2]))?;
    let db = &ix.db_state;
    let tables: serde_json::Map<String, Json> = db
        .table_names()
        .into_iter()
        .map(|t| {
            let rows: Vec<Json> = db
                .get_table(&t)
                .iter()
                .map(|r| Json::Object(r.iter().map(|(k, v)| (k.clone(), v.to_json().unwrap_or(Json::Null))).collect()))
                .collect();
            (t.clone(), json!({"columns": db.get_columns(&t), "rows": rows}))
        })
        .collect();
    let f = &ix.entities;
    let allowed: serde_json::Map<String, Json> = ["caller_only", "all", "off"]
        .iter()
        .map(|m| (m.to_string(), json!(f.allowed_ctors(m).unwrap_or_default().iter().collect::<Vec<_>>())))
        .collect();
    let data = json!({
        "skeleton": {
            "project": ix.project,
            "nodes": ix.n.keys().collect::<Vec<_>>(),
            "handlers": ix.handlers.iter().map(|(h, v, s)| json!([h, v, s])).collect::<Vec<_>>(),
            "module": ix.module,
            "units": sets(ix.units.iter()),
            "unit_of": ix.module.keys().map(|m| (m.clone(), json!(ix.unit_of(m)))).collect::<serde_json::Map<_, _>>(),
            "cha": ix.over.keys().map(|m| (m.clone(), json!(ix.cha(m).iter().collect::<Vec<_>>()))).collect::<serde_json::Map<_, _>>(),
            "calls": sets(ix.calls.iter()),
            "over": sets(ix.over.iter()),
            "wiring": ix.wiring.iter().map(|(k, v)| (k.clone(), sets(v.iter()))).collect::<serde_json::Map<_, _>>(),
            "context": ix.context,
        },
        "db": tables,
        "entities": {
            "entities": f.entities.iter().map(|(k, v)| (k.clone(), entity(v))).collect::<serde_json::Map<_, _>>(),
            "calls_by_method": f.calls_by_method.iter().map(|(k, v)| (k.clone(), json!(v.iter().map(call).collect::<Vec<_>>()))).collect::<serde_json::Map<_, _>>(),
            "ctors_with_project_calls": f.ctors_with_project_calls.iter().collect::<Vec<_>>(),
            "allowed_ctors": allowed,
        },
    });
    std::fs::write(&a[3], dumps_indent1(&sort_keys(&data)) + "\n")?;
    Ok(())
}

//! Загрузка исходников проекта: обход каталога, разбор tree-sitter.

use std::fs;
use std::path::Path;

use anyhow::{Context, Result};

use crate::ast::{new_parser, Doc};

/// Все `.java` под корнем (относительные пути через `/`), по возрастанию байтов пути. Символьные ссылки не обходим.
pub fn list_java(root: &Path) -> Result<Vec<String>> {
    fn walk(dir: &Path, prefix: &str, out: &mut Vec<String>) -> Result<()> {
        for entry in fs::read_dir(dir).with_context(|| format!("каталог {}", dir.display()))? {
            let entry = entry?;
            let name = entry.file_name().to_string_lossy().into_owned();
            let rel = if prefix.is_empty() { name.clone() } else { format!("{prefix}/{name}") };
            let ft = entry.file_type()?;
            if ft.is_dir() {
                walk(&entry.path(), &rel, out)?;
            } else if ft.is_file() && name.ends_with(".java") {
                out.push(rel);
            }
        }
        Ok(())
    }
    let mut out = Vec::new();
    walk(root, "", &mut out)?;
    out.sort();
    Ok(out)
}

fn parse_file(root: &Path, rel: &str, parser: &mut tree_sitter::Parser) -> Option<Doc> {
    let bytes = match fs::read(root.join(rel)) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("Parse error, skipped: {rel}: {e}");
            return None;
        }
    };
    let module = rel.split('/').next().unwrap_or("").to_string();
    Doc::parse(parser, rel.to_string(), module, bytes)
}

/// Файлы `src/main/java` проекта: их разбирают и IR тел, и сканер сущностей.
pub fn parse_main(root: &Path, files: &[String]) -> Vec<Doc> {
    let mut parser = new_parser();
    files
        .iter()
        .filter(|r| r.contains("/src/main/java/"))
        .filter_map(|r| parse_file(root, r, &mut parser))
        .collect()
}

/// Файлы со словом `enum ` (общий обход перечислений, как `EnumResolver.scanEnums`).
pub fn parse_enum_files(root: &Path, files: &[String]) -> Vec<Doc> {
    let mut parser = new_parser();
    files
        .iter()
        .filter(|r| fs::read(root.join(r)).map(|b| String::from_utf8_lossy(&b).contains("enum ")).unwrap_or(false))
        .filter_map(|r| parse_file(root, r, &mut parser))
        .collect()
}

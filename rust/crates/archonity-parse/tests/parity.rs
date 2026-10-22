//! Паритет разбора исходников (ADR-009): `archonity-parse --mode all` воспроизводит закоммиченные `data/ir/*.json` и
//! `data/entity_ir.json` байт в байт. Нужен пакет задачи в `hackaton/tt-challenge/` (скелет и исходники); без него
//! тест пропускается с сообщением.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..").canonicalize().expect("корень репозитория")
}

/// Единственный файл или каталог в `dir`, подходящий под `keep` (скелет `*.json.gz`, каталог исходников).
fn only(dir: &Path, keep: impl Fn(&Path) -> bool) -> Option<PathBuf> {
    let mut found: Vec<PathBuf> = fs::read_dir(dir).ok()?.filter_map(|e| e.ok().map(|e| e.path())).filter(|p| keep(p)).collect();
    (found.len() == 1).then(|| found.remove(0))
}

fn read_dir_sorted(dir: &Path) -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir(dir)
        .unwrap_or_else(|e| panic!("{}: {e}", dir.display()))
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".json"))
        .collect();
    names.sort();
    names
}

#[test]
fn ir_and_entities_match_committed() {
    let root = repo_root();
    let pkg = root.join("hackaton/tt-challenge");
    let skeleton = only(&pkg.join("skeleton"), |p| p.to_string_lossy().ends_with(".json.gz"));
    let targets = only(&pkg.join("targets"), |p| p.is_dir());
    let (Some(skeleton), Some(targets)) = (skeleton, targets) else {
        eprintln!("пропуск: нет пакета задачи в {} (скелет и исходники)", pkg.display());
        return;
    };
    let out = std::env::temp_dir().join(format!("archonity-parse-parity-{}", std::process::id()));
    let _ = fs::remove_dir_all(&out);
    let status = Command::new(env!("CARGO_BIN_EXE_archonity-parse"))
        .args(["--mode", "all", "--targets-dir"])
        .arg(&targets)
        .arg("--skeleton")
        .arg(&skeleton)
        .arg("-o")
        .arg(&out)
        .status()
        .expect("запуск archonity-parse");
    assert!(status.success(), "archonity-parse завершился с {status}");

    let committed = root.join("data/ir");
    let names = read_dir_sorted(&committed);
    assert_eq!(read_dir_sorted(&out.join("ir")), names, "набор файлов IR отличается от data/ir");
    let diff: Vec<&String> =
        names.iter().filter(|n| fs::read(out.join("ir").join(n)).unwrap() != fs::read(committed.join(n)).unwrap()).collect();
    assert!(diff.is_empty(), "IR отличается от data/ir: {diff:?}");
    assert!(
        fs::read(out.join("entity_ir.json")).unwrap() == fs::read(root.join("data/entity_ir.json")).unwrap(),
        "entity_ir.json отличается от data/entity_ir.json"
    );
    let _ = fs::remove_dir_all(&out);
}

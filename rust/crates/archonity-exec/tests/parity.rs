//! Паритет движка (ADR-008): `archonity-exec` по шагам M1 сценариев S0–S7 (`tests/data/step_requests_raw.json`, их
//! пишет `run_eval.py --engine rust` из кеша LLM) строит `submission.json` байт в байт как рекорд
//! `eval/records/submission_p27_1.00000.json` (sha256 `94463c41…`). Умолчания правил — как у `run_eval.py`.
//! Нужен пакет задачи в `hackaton/tt-challenge/` (скелет, дамп БД, исходники); без него тест пропускается с сообщением.
//!
//! Шаги M1 поменялись (промпт, карточки, поиск) — обновить вход: `python run_eval.py --engine rust -o <папка>/x.json`,
//! затем скопировать `<папка>/step_requests_raw.json` сюда; рекорд при этом тоже новый.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const RECORD: &str = "eval/records/submission_p27_1.00000.json";

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..").canonicalize().expect("корень репозитория")
}

/// Единственный файл или каталог в `dir`, подходящий под `keep` (скелет `*.json.gz`, каталог исходников).
fn only(dir: &Path, keep: impl Fn(&Path) -> bool) -> Option<PathBuf> {
    let mut found: Vec<PathBuf> = fs::read_dir(dir).ok()?.filter_map(|e| e.ok().map(|e| e.path())).filter(|p| keep(p)).collect();
    (found.len() == 1).then(|| found.remove(0))
}

#[test]
fn submission_matches_record() {
    let root = repo_root();
    let pkg = root.join("hackaton/tt-challenge");
    let skeleton = only(&pkg.join("skeleton"), |p| p.to_string_lossy().ends_with(".json.gz"));
    let targets = only(&pkg.join("targets"), |p| p.is_dir());
    let (Some(skeleton), Some(targets)) = (skeleton, targets) else {
        eprintln!("пропуск: нет пакета задачи в {} (скелет и исходники)", pkg.display());
        return;
    };
    let out = std::env::temp_dir().join(format!("archonity-exec-parity-{}", std::process::id()));
    let _ = fs::remove_dir_all(&out);
    let status = Command::new(env!("CARGO_BIN_EXE_archonity-exec"))
        .arg("--step-requests")
        .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/data/step_requests_raw.json"))
        .arg("--skeleton")
        .arg(&skeleton)
        .arg("--targets")
        .arg(&targets)
        .arg("--ir-dir")
        .arg(root.join("data/ir"))
        .arg("--entity-ir")
        .arg(root.join("data/entity_ir.json"))
        .arg("--configs-topology")
        .arg(root.join("facts/configs_topology.json"))
        .arg("-o")
        .arg(out.join("submission.json"))
        .status()
        .expect("запуск archonity-exec");
    assert!(status.success(), "archonity-exec завершился с {status}");

    assert_eq!(fs::read_to_string(out.join("exec_failures.json")).unwrap().trim(), "[]", "сбои шагов или сценариев");
    let got = fs::read(out.join("submission.json")).unwrap();
    assert!(got == fs::read(root.join(RECORD)).unwrap(), "submission.json отличается от рекорда {RECORD}");
    let _ = fs::remove_dir_all(&out);
}

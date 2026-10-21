//! `archonity-exec` (ADR-008): M4, R20, Spring Security, R19, M5 и запись `submission.json`, `evidence.json`,
//! `decisions.json`. Вход — `step_requests_raw.json` от Python-части (M1). Владелец — Паша.

// Этап 0: функции с todo!() ещё не вызываются. Паша убирает атрибут, когда подключит цикл сценариев.
#![allow(dead_code)]

mod binding;
mod catalog;
mod pipeline;
mod projection;
mod security;

use std::path::PathBuf;

use anyhow::Result;
use clap::Parser;

#[derive(Parser, Debug)]
#[command(name = "archonity-exec", about = "Исполнение шагов сценариев по IR и построение выдачи")]
struct Args {
    /// `step_requests_raw.json`: шаги каждого сценария до R20.
    #[arg(long)]
    step_requests: PathBuf,
    /// Скелет (`.json.gz`).
    #[arg(long)]
    skeleton: PathBuf,
    /// Исходники проекта (каталог UI).
    #[arg(long)]
    targets: Option<PathBuf>,
    /// IR тел методов.
    #[arg(long, default_value = "data/ir")]
    ir_dir: PathBuf,
    /// `entity_ir.json`.
    #[arg(long)]
    entity_ir: Option<PathBuf>,
    /// Дамп БД; по умолчанию рядом со скелетом.
    #[arg(long)]
    db_dump: Option<PathBuf>,
    /// Файл выдачи; `evidence.json` и `decisions.json` — рядом.
    #[arg(short, long)]
    out: PathBuf,
    /// Флаги правил `name=value` (имена `RuntimeRules`, например `constructors=caller_only`).
    #[arg(long = "rule")]
    rules: Vec<String>,
    /// Вместо M4 брать сырые рёбра и журнал шагов из `raw_steps.json` оракула Python (проверка R19, M5, записи файлов).
    #[arg(long)]
    replay: Option<PathBuf>,
}

fn main() -> Result<()> {
    let args = Args::parse();
    pipeline::run(&args.into())
}

/// Параметры прогона для `pipeline::run`.
pub struct RunConfig {
    pub step_requests: PathBuf,
    pub skeleton: PathBuf,
    pub targets: Option<PathBuf>,
    pub ir_dir: PathBuf,
    pub entity_ir: Option<PathBuf>,
    pub db_dump: Option<PathBuf>,
    pub out: PathBuf,
    pub rules: Vec<String>,
    pub replay: Option<PathBuf>,
}

impl From<Args> for RunConfig {
    fn from(a: Args) -> RunConfig {
        RunConfig {
            step_requests: a.step_requests,
            skeleton: a.skeleton,
            targets: a.targets,
            ir_dir: a.ir_dir,
            entity_ir: a.entity_ir,
            db_dump: a.db_dump,
            out: a.out,
            rules: a.rules,
            replay: a.replay,
        }
    }
}

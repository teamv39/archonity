//! `archonity-parse`: IR тел методов (`data/ir/<module>.json`) и факты о сущностях (`data/entity_ir.json`)
//! по исходникам проекта и скелету. Перенос `archparse` (ADR-009).

mod ast;
mod body;
mod enumres;
mod index;
mod jsonw;
mod lit;
mod skeleton;
mod source;
mod writer;

use std::fs;
use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Parser, ValueEnum};

#[derive(Clone, Copy, ValueEnum, PartialEq)]
enum Mode {
    /// IR тел всех методов скелета: папка `<module>.json`.
    Bodies,
    /// сущности и вызовы репозиториев: файл `entity_ir.json`.
    Entities,
    /// оба артефакта: `-o` — папка `data`.
    All,
}

#[derive(Parser)]
#[command(name = "archonity-parse", about = "Разбор исходников проекта в IR тел методов и entity_ir.json")]
struct Cli {
    /// корень исходников проекта
    #[arg(long = "targets-dir", alias = "repo-root")]
    targets_dir: PathBuf,
    /// скелет `.json.gz` или `.json`
    #[arg(long)]
    skeleton: PathBuf,
    #[arg(long, value_enum, default_value = "bodies")]
    mode: Mode,
    /// bodies: папка IR; entities: файл; all: папка артефактов (`ir/`, `entity_ir.json`)
    #[arg(short, long)]
    output: Option<PathBuf>,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let sk = skeleton::Skeleton::load(&cli.skeleton)?;
    let files = source::list_java(&cli.targets_dir)?;
    let docs = source::parse_main(&cli.targets_dir, &files);
    eprintln!("archonity-parse: разобрано {} файлов src/main/java", docs.len());

    if cli.mode == Mode::Bodies || cli.mode == Mode::All {
        let out_dir = match (cli.mode, &cli.output) {
            (Mode::All, Some(o)) => o.join("ir"),
            (_, Some(o)) => o.clone(),
            (_, None) => PathBuf::from("data/ir"),
        };
        let r = writer::build(&sk, &docs);
        fs::create_dir_all(&out_dir)?;
        for (module, doc) in &r.modules {
            fs::write(out_dir.join(format!("{module}.json")), jsonw::to_string(doc)).with_context(|| format!("запись {module}"))?;
        }
        println!(
            "Finished! {} methods in {} modules, {} skeleton call sites, {} ircalls -> {}",
            r.methods,
            r.modules.len(),
            r.call_sites,
            r.ir_calls,
            out_dir.display()
        );
        println!(
            "Coverage: {} skeleton methods missing, {} declarations unmatched, {} call sites uncovered, {} duplicated, {} foreign",
            r.missing_methods.len(),
            r.unmatched_declarations.len(),
            r.uncovered_call_sites.len(),
            r.duplicate_call_sites.len(),
            r.foreign_call_sites.len()
        );
        for (tag, list, n) in [
            ("missing", &r.missing_methods, 20),
            ("unmatched", &r.unmatched_declarations, 20),
            ("uncovered", &r.uncovered_call_sites, 20),
            ("duplicate", &r.duplicate_call_sites, 10),
            ("foreign", &r.foreign_call_sites, 10),
        ] {
            for m in list.iter().take(n) {
                println!("  {tag}: {m}");
            }
        }
    }
    Ok(())
}

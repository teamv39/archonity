//! Шаг сценария для исполнителя M4 (`engine/executor/step.py`): `StepRequest` -> аргументы обработчика -> события -> рёбра.
//!
//! Аргументы обработчика:
//! - `@RequestBody` — DTO из `params` шага и ссылок `refs` (поля, которых не определил шаг, неизвестны);
//! - `@PathVariable` — по имени из `params`, ссылок или текущего пользователя;
//! - `@RequestHeader` — неизвестно.
//!
//! Ссылки `<first|second|new>_of_step_<n>` разрешаются по миру M4: `new` — сущность, сохранённая шагом n,
//! `first`/`second` — элемент результата обработчика шага n.

use std::collections::{BTreeSet, HashMap};
use std::path::Path;
use std::rc::Rc;

use anyhow::Result;
use archonity_io::decisions::detail;
use archonity_io::{jx, DecisionLedger, SkeletonIndex};
use archonity_model::names::simple_name;
use archonity_model::values::*;
use archonity_model::{group_sent, BodyGroup, RuleFlags, ScenarioContext, StepEdges, StepRequest};
use indexmap::IndexMap;
use regex::Regex;
use serde_json::Value as Json;

use crate::envelope::Envelope;
use crate::interpreter::{err, Exc, Interpreter, Sink, R};
use crate::schema::EntitySchema;

/// Параметры шага: имя -> JSON-значение (без null).
pub type Params = IndexMap<String, Json>;

fn wordy(s: &str) -> bool {
    thread_local! { static W: Regex = Regex::new(r"^[A-Za-z][A-Za-z ,.'-]*$").unwrap(); }
    W.with(|re| re.is_match(s))
}

/// Имя поля без регистра и разделителей: `userName`, `username`, `user_name` -> `username`.
fn norm(name: &str) -> String {
    name.to_lowercase().chars().filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit()).collect()
}

/// Ключ сравнения строки шага со значением мира БД: только строчные буквы и цифры.
fn canon(s: &str) -> String {
    s.to_lowercase().chars().filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit()).collect()
}

fn parse_ref(r: &str) -> Option<(&str, i64)> {
    thread_local! { static R: Regex = Regex::new(r"^(first|second|new)_of_step_(\d+)$").unwrap(); }
    R.with(|re| {
        re.captures(r).map(|m| {
            let pick = match &m[1] {
                "first" => "first",
                "second" => "second",
                _ => "new",
            };
            (pick, m[2].parse::<i64>().unwrap_or(0))
        })
    })
}

/// Слово позиции или повтора в тексте шага («the first order», «another», «the second»); «first-class» — не позиция.
/// Как `_POSITION` в `engine/executor/step.py` (R22).
fn has_position_word(action: &str) -> bool {
    thread_local! {
        static P: fancy_regex::Regex = fancy_regex::Regex::new(
            r"(?i)\b(?:first|second|third|fourth|fifth|last|next|previous|another|other|same|one more|\d+(?:st|nd|rd|th))\b(?!-)",
        )
        .unwrap();
    }
    P.with(|re| re.is_match(action).unwrap_or(false))
}

/// Всё состояние `StepExecutor`, кроме интерпретатора: методы получают `&mut Interpreter` параметром, чтобы замыкание
/// аргументов обработчика могло заимствовать одно без другого.
pub struct StepCore {
    pub index: Rc<SkeletonIndex>,
    pub schema: EntitySchema,
    pub results: HashMap<i64, Value>,
    pub current_user: Option<String>,
    pub written: IndexMap<String, Value>,
    pub handlers: HashMap<i64, String>,
    pub step_params: HashMap<i64, Params>,
    pub step_refs: HashMap<i64, IndexMap<String, String>>,
    pub saved: HashMap<i64, Vec<(String, Shared<Obj>)>>,
    pub unknowns: IndexMap<String, Vec<Json>>,
    pub sid: String,
    login_ids: IndexMap<String, Vec<String>>,
    login_blanks: BTreeSet<String>,
    reach: HashMap<(String, bool), BTreeSet<String>>,
    remote_of: Option<HashMap<String, BTreeSet<String>>>, // метод -> обработчики его межсервисных вызовов
    dedupe: HashMap<(String, Option<String>), Vec<String>>,
    verb: Option<String>,
    user_name: Option<String>,
    body_src: IndexMap<String, String>,
    body_groups: Vec<BodyGroup>,
}

pub struct StepExecutor {
    pub it: Interpreter,
    pub core: StepCore,
}

impl StepExecutor {
    /// `ir_dir` — `data/ir/`; `targets_root` — исходники проекта (каталог UI), если есть.
    pub fn new(index: Rc<SkeletonIndex>, flags: RuleFlags, ir_dir: &Path, targets_root: Option<&Path>) -> Result<StepExecutor> {
        let it = Interpreter::new(index.clone(), flags, ir_dir, targets_root)?;
        let schema = EntitySchema::new(Some(&index));
        let login_ids = login_principal_ids(&index);
        let login_blanks = context_login_blanks(&index.raw_context);
        Ok(StepExecutor {
            it,
            core: StepCore {
                index,
                schema,
                results: HashMap::new(),
                current_user: None,
                written: IndexMap::new(),
                handlers: HashMap::new(),
                step_params: HashMap::new(),
                step_refs: HashMap::new(),
                saved: HashMap::new(),
                unknowns: IndexMap::new(),
                sid: "S?".to_string(),
                login_ids,
                login_blanks,
                reach: HashMap::new(),
                remote_of: None,
                dedupe: HashMap::new(),
                verb: None,
                user_name: None,
                body_src: IndexMap::new(),
                body_groups: Vec::new(),
            },
        })
    }

    /// Мир БД сценария: копия дампа.
    pub fn begin_scenario(&mut self, sid: &str) {
        let c = &mut self.core;
        c.sid = sid.to_string();
        self.it.begin_scenario(c.index.db_state.fork());
        c.results = HashMap::new();
        c.current_user = None;
        c.written = IndexMap::new();
        c.handlers = HashMap::new();
        c.step_params = HashMap::new();
        c.step_refs = HashMap::new();
        c.saved = HashMap::new();
        c.unknowns.insert(sid.to_string(), Vec::new());
    }

    /// Исполняет шаг (запрос после R20) и пишет решения шага в журнал. Рёбра — до Spring Security и M5.
    pub fn run_step(&mut self, req: &StepRequest, ctx: &ScenarioContext, ledger: &mut DecisionLedger) -> Result<StepEdges> {
        let StepExecutor { it, core } = self;
        let n = req.step;
        let handler = req.handler.clone();
        let params: Params = req.params.iter().filter(|(_, v)| !v.is_null()).map(|(k, v)| (k.clone(), v.clone())).collect();
        core.user_name = ctx.user_name.clone();
        core.verb = req.http.get("method").cloned();
        core.body_src = req.body_src.clone();
        core.body_groups = req.body_groups.clone();
        let refs = if it.flags.ref_unpositioned { core.prefer_created(n, &req.action, &req.refs) } else { req.refs.clone() };
        let expected = req.expected_outcome.clone();
        let before = it.world.as_ref().map(|w| w.saved.len()).unwrap_or(0);
        let snapshot = if it.flags.m4_success_retry { it.world.as_ref().map(|w| w.db.fork()) } else { None };
        let (mut sink, mut ret) = {
            let (c, p, r) = (&mut *core, &params, &refs);
            it.run_handler(&handler, &mut |it| c.handler_args(it, &handler, p, r, ctx), &expected, Some(n))
                .map_err(exc_to_anyhow)?
        };
        let any_str = params.values().any(Json::is_string);
        if let (Some(snap), true) = (&snapshot, expected != "refused" && any_str && is_failure(&ret, it.envelope.as_ref())) {
            // Шаг по тексту успешен, а по конкретным значениям отказал: откат мира и повтор с нормализованными,
            // затем неизвестными строковыми параметрами.
            let first: Params = params
                .iter()
                .map(|(k, v)| match v {
                    Json::String(s) if wordy(s) => (k.clone(), Json::String(core.world_string(it, s))),
                    _ => (k.clone(), v.clone()),
                })
                .collect();
            let second: Params = params.iter().filter(|(_, v)| !matches!(v, Json::String(s) if wordy(s))).map(|(k, v)| (k.clone(), v.clone())).collect();
            let third: Params = params.iter().filter(|(_, v)| !v.is_string()).map(|(k, v)| (k.clone(), v.clone())).collect();
            for (level, relaxed) in [(1, first), (2, second), (3, third)] {
                if json_map_eq(&relaxed, &params) {
                    continue;
                }
                if let Some(w) = it.world.as_mut() {
                    w.db = snap.fork();
                    w.saved.truncate(before);
                }
                let mut dropped: Vec<&String> = params.keys().filter(|k| relaxed.get(*k) != params.get(*k)).collect();
                dropped.sort();
                let (c, r) = (&mut *core, &refs);
                let rel = &relaxed;
                let (s2, r2) = it
                    .run_handler(&handler, &mut |it| c.handler_args(it, &handler, rel, r, ctx), &expected, Some(n))
                    .map_err(exc_to_anyhow)?;
                sink = s2;
                ret = r2;
                sink.unknowns.push(serde_json::json!({
                    "method": handler, "branch": "step", "line": Json::Null,
                    "decided": format!("success_retry{level}:changed_params={}", dropped.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(",")),
                }));
                if !is_failure(&ret, it.envelope.as_ref()) {
                    break;
                }
            }
        }
        core.results.insert(n, ret.clone());
        core.handlers.insert(n, handler.clone());
        core.step_params.insert(n, params);
        core.step_refs.insert(n, refs);
        let saved: Vec<(String, Shared<Obj>)> = it.world.as_ref().map(|w| w.saved[before.min(w.saved.len())..].to_vec()).unwrap_or_default();
        core.saved.insert(n, saved);
        // Текущий пассажир — из ответа входа, как его берёт UI (client_id = data.userId)
        if let Some(uid) = core.logged_in_user(&sink, &ret, it.envelope.as_ref()) {
            core.current_user = Some(uid);
        }
        let sid = core.sid.clone();
        for u in &sink.unknowns {
            let mut u = u.clone();
            if let Some(o) = u.as_object_mut() {
                o.insert("step".into(), Json::from(n));
            }
            core.unknowns.entry(sid.clone()).or_default().push(u);
        }
        emit(&sink, ledger)
    }
}

fn exc_to_anyhow(e: Exc) -> anyhow::Error {
    match e {
        Exc::Abort => anyhow::anyhow!("_Abort"),
        Exc::Err(m) => anyhow::anyhow!(m),
    }
}

fn json_map_eq(a: &Params, b: &Params) -> bool {
    a.len() == b.len() && a.iter().all(|(k, v)| b.get(k).is_some_and(|w| json_eq(v, w)))
}

/// `==` Python для JSON-значений: числа сравниваются по значению.
fn json_eq(a: &Json, b: &Json) -> bool {
    match (a, b) {
        (Json::Number(x), Json::Number(y)) => x.as_f64() == y.as_f64(),
        _ => a == b,
    }
}

fn emit(sink: &Sink, ledger: &mut DecisionLedger) -> Result<StepEdges> {
    let mut edges = StepEdges::default();
    edges.methods = sink.methods.keys().cloned().collect();
    edges.calls = sink.calls.keys().cloned().collect();
    edges.remote = sink.remote.keys().cloned().collect();
    edges.data = sink.data.keys().cloned().collect();
    for (rel, s, t, st, rule) in &sink.prunes {
        let s = if rel == "executes" { format!("scenario:{}", ledger.scenario_id()?) } else { s.clone() };
        ledger.prune(rel, &s, t, st, rule, Default::default())?;
    }
    for (rel, m) in [("calls", &sink.calls), ("remote", &sink.remote), ("data", &sink.data)] {
        let mut es: Vec<_> = m.iter().collect();
        es.sort_by(|a, b| a.0.cmp(b.0));
        for ((s, t), (st, rule)) in es {
            ledger.include(rel, s, t, st, rule, Default::default())?;
        }
    }
    let mut ms: Vec<_> = sink.methods.iter().collect();
    ms.sort_by(|a, b| a.0.cmp(b.0));
    for (m, (st, rule, via)) in ms {
        let d = detail(&[("via", via.clone().map(Json::String).unwrap_or(Json::Null))]);
        ledger.execute(m, st, rule, d)?;
    }
    Ok(edges)
}

// --- ответ обработчика ---------------------------------------------------------------------------------------------------

/// Ответ обработчика — отказ: обёртка проекта со статусом, известным и не равным успеху.
pub fn is_failure(ret: &Value, env: Option<&Envelope>) -> bool {
    let mut v = ret.clone();
    for _ in 0..3 {
        if let Value::Wrapper(w) = &v {
            let b = w.borrow().body.clone();
            v = b;
        }
    }
    if let (Some(env), Value::Obj(o)) = (env, &v) {
        let o = o.borrow();
        if env.is_type(o.ty.as_deref()) {
            return matches!(o.fields.get(&env.status), Some(Value::Int(st)) if *st != env.success);
        }
    }
    false
}

/// Данные ответа обработчика: ResponseEntity -> обёртка проекта -> её поле данных.
pub fn payload(v: &Value, env: Option<&Envelope>) -> Value {
    let mut v = v.clone();
    for _ in 0..4 {
        let next = match &v {
            Value::Wrapper(w) => w.borrow().body.clone(),
            Value::Obj(o) if env.is_some_and(|e| e.data.is_some() && e.is_type(o.borrow().ty.as_deref())) => {
                o.borrow().get(env.unwrap().data.as_deref().unwrap())
            }
            Value::Optional(o) => o.borrow().value.clone(),
            _ => break,
        };
        v = next;
    }
    v
}

/// Объект вида `kind`: по имени типа или по известному ID-полю вида.
fn obj_is_kind(o: &Obj, kind: &str, schema: &EntitySchema) -> bool {
    if schema.is_kind(o.ty.as_deref(), kind) {
        return true;
    }
    match schema.primary_id_field(kind) {
        Some(p) => matches!(o.fields.get(&p), Some(Value::Str(_))),
        None => false,
    }
}

/// Объекты вида `kind` в результате шага: сам объект, элементы списка или поля (на 2 уровня).
fn find_kind(v: &Value, kind: &str, depth: usize, schema: &EntitySchema) -> Vec<Value> {
    if depth > 2 || v.is_null() || v.is_unknown() {
        return Vec::new();
    }
    match v {
        Value::List(l) => {
            let items = l.borrow().items.clone();
            let direct: Vec<Value> = items.iter().filter(|x| matches!(x, Value::Obj(o) if obj_is_kind(&o.borrow(), kind, schema))).cloned().collect();
            if !direct.is_empty() {
                return direct;
            }
            let mut out = Vec::new();
            for x in &items {
                out.extend(find_kind(x, kind, depth + 1, schema).into_iter().take(1));
            }
            out
        }
        Value::Obj(o) => {
            if schema.is_kind(o.borrow().ty.as_deref(), kind) {
                return vec![v.clone()];
            }
            let fields: Vec<(String, Value)> = o.borrow().fields.iter().map(|(k, x)| (k.clone(), x.clone())).collect();
            for (k, x) in fields {
                if matches!(x, Value::Obj(_) | Value::List(_)) {
                    if let Value::Obj(xo) = &x {
                        if schema.is_kind(xo.borrow().ty.as_deref(), kind) || k.to_lowercase().contains(kind) {
                            return vec![x.clone()];
                        }
                    }
                    let r = find_kind(&x, kind, depth + 1, schema);
                    if !r.is_empty() {
                        return r;
                    }
                }
            }
            Vec::new()
        }
        _ => Vec::new(),
    }
}

// --- вход ---------------------------------------------------------------------------------------------------------------

/// Методы входа (call_site `authenticate` у `AuthenticationManager`) -> поля `@Id` классов `UserDetails` модуля.
fn login_principal_ids(index: &SkeletonIndex) -> IndexMap<String, Vec<String>> {
    const AUTH: &str = "org.springframework.security.authentication.AuthenticationManager";
    let nodes = &index.n;
    let mut entries: BTreeSet<String> = BTreeSet::new();
    for n in nodes.values() {
        if jx::str_(n, "kind") == Some("call_site") && jx::str_(n, "callee") == Some("authenticate") && jx::str_(n, "receiver_type") == Some(AUTH) {
            if let Some(m) = jx::str_(n, "method").filter(|m| !m.is_empty()) {
                entries.insert(m.to_string());
            }
        }
    }
    let users: HashMap<&str, Option<&str>> = nodes
        .iter()
        .filter(|(_, n)| jx::str_(n, "kind") == Some("type") && jx::strs(n, "implements_raw").contains(&"UserDetails"))
        .map(|(id, n)| (id.as_str(), jx::str_(n, "module")))
        .collect();
    let mut principals: HashMap<Option<&str>, BTreeSet<String>> = HashMap::new();
    for n in nodes.values() {
        if jx::str_(n, "kind") == Some("field") {
            if let Some(module) = jx::str_(n, "owner").and_then(|o| users.get(o)) {
                let has_id = jx::arr(n, "annotations").iter().any(|a| {
                    let name = if a.is_object() { jx::str_(a, "name") } else { a.as_str() };
                    matches!(name, Some("Id" | "EmbeddedId"))
                });
                if has_id {
                    principals.entry(*module).or_default().insert(jx::str_(n, "name").unwrap_or("").to_string());
                }
            }
        }
    }
    entries
        .into_iter()
        .map(|m| {
            let module = nodes.get(&m).and_then(|n| jx::str_(n, "module"));
            let ids = principals.get(&module).map(|s| s.iter().cloned().collect()).unwrap_or_default();
            (m, ids)
        })
        .collect()
}

/// Поля, которых при входе нет, по тексту context скелета: «no verification code at login» -> `verificationcode`.
fn context_login_blanks(context: &Json) -> BTreeSet<String> {
    let re = Regex::new(r"\bno ([A-Za-z][A-Za-z ]*?) at login").unwrap();
    let mut out = BTreeSet::new();
    if let Some(o) = context.as_object() {
        for v in o.values() {
            if let Some(t) = v.as_str() {
                for m in re.captures_iter(t) {
                    out.insert(norm(&m[1]));
                }
            }
        }
    }
    out
}

/// Выражения вызова в IR тела метода, в порядке обхода.
fn call_exprs<'a>(x: &'a Json, out: &mut Vec<&'a Json>) {
    match x {
        Json::Object(o) => {
            if o.get("call").and_then(Json::as_str).is_some_and(|c| c.starts_with("call:")) && o.contains_key("callee") {
                out.push(x);
            }
            for v in o.values() {
                if v.is_object() || v.is_array() {
                    call_exprs(v, out);
                }
            }
        }
        Json::Array(a) => {
            for v in a {
                call_exprs(v, out);
            }
        }
        _ => {}
    }
}

impl StepCore {
    // --- ссылки ------------------------------------------------------------------------------------------------------

    pub fn resolve_ref(&mut self, it: &mut Interpreter, kind: &str, r: &str, depth: usize) -> R<Option<Value>> {
        let Some((pick, n)) = parse_ref(r) else { return Ok(None) };
        let saved_n = self.saved.get(&n).cloned().unwrap_or_default();
        if pick == "new" {
            let cands: Vec<&(String, Shared<Obj>)> = saved_n.iter().filter(|(fqn, _)| self.schema.is_kind(Some(fqn), kind)).collect();
            if !cands.is_empty() {
                let top = cands.iter().map(|(fqn, _)| self.schema.kind_rank(Some(fqn), kind)).max().unwrap();
                let sel: Vec<&&(String, Shared<Obj>)> = cands.iter().filter(|(fqn, _)| self.schema.kind_rank(Some(fqn), kind) == top).collect();
                return Ok(Some(Value::Obj(sel.last().unwrap().1.clone())));
            }
        }
        let idx = if pick == "second" { 1 } else { 0 };
        let found = find_kind(&payload(self.results.get(&n).unwrap_or(&Value::Null), it.envelope.as_ref()), kind, 0, &self.schema);
        if !found.is_empty() {
            let ent = found.get(idx).unwrap_or(&found[0]).clone();
            if !self.entity_id(it, &ent, kind, 0)?.is_unknown() {
                return Ok(Some(ent));
            }
            // Контекст скелета: выбор «первого» рейса/контакта/блюда не меняет исполненный код, поэтому при неизвестном
            // ID берём строку таблицы сущности этого вида в сервисе шага
            if let Some(row_ent) = self.table_entity(it, n, kind, idx)? {
                let ent_o = match &ent {
                    Value::Obj(o) => o.clone(),
                    _ => return Ok(Some(ent)),
                };
                let fields = row_ent.borrow().fields.clone();
                let merged = shared(Obj::new(ent_o.borrow().ty.clone(), fields, true));
                for (k, v) in ent_o.borrow().fields.iter() {
                    if !v.is_unknown() && !v.is_null() {
                        merged.borrow_mut().fields.insert(k.clone(), v.clone());
                    }
                }
                return Ok(Some(Value::Obj(merged)));
            }
            // Ответ шага без ID — не сущность, а сводка («доплатите разницу»: `new Order()` с одной суммой): сущность —
            // та, над которой работал шаг n (его собственная ссылка того же вида), если у неё ID известен
            if it.flags.ref_idless_result {
                let prev = self.step_refs.get(&n).and_then(|m| m.get(kind)).cloned();
                if let Some(prev) = prev.filter(|p| !p.is_empty() && p != r && depth < 4) {
                    if let Some(alt) = self.resolve_ref(it, kind, &prev, depth + 1)? {
                        if !self.entity_id(it, &alt, kind, 0)?.is_unknown() {
                            return Ok(Some(alt));
                        }
                    }
                }
            }
            return Ok(Some(ent));
        }
        let saved_c: Vec<&(String, Shared<Obj>)> = saved_n.iter().filter(|(fqn, _)| self.schema.is_kind(Some(fqn), kind)).collect();
        let top = saved_c.iter().map(|(fqn, _)| self.schema.kind_rank(Some(fqn), kind)).max().unwrap_or(0);
        let saved: Vec<&Shared<Obj>> = saved_c.iter().filter(|(fqn, _)| self.schema.kind_rank(Some(fqn), kind) == top).map(|(_, o)| o).collect();
        if !saved.is_empty() {
            let o = if pick == "new" { saved.last().unwrap() } else { saved[idx.min(saved.len() - 1)] };
            return Ok(Some(Value::Obj((*o).clone())));
        }
        // Шаг n не создавал и не возвращал сущность этого вида: та, на которую ссылался сам шаг n
        let prev = self.step_refs.get(&n).and_then(|m| m.get(kind)).cloned();
        if let Some(prev) = prev.filter(|p| !p.is_empty() && p != r && depth < 4) {
            if let Some(ent) = self.resolve_ref(it, kind, &prev, depth + 1)? {
                return Ok(Some(ent));
            }
        }
        Ok(None)
    }

    fn table_entity(&self, it: &mut Interpreter, n: i64, kind: &str, idx: usize) -> R<Option<Shared<Obj>>> {
        let handler = self.handlers.get(&n).cloned().unwrap_or_default();
        let module = self.index.n.get(&handler).and_then(|x| jx::str_(x, "module")).map(str::to_string);
        let Some(w) = it.world.take() else { return Ok(None) };
        let mut tables: Vec<(String, String)> = w.table_of.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        tables.sort();
        let mut result: Option<Shared<Obj>> = None;
        let mut pending: Option<Exc> = None;
        for (fqn, table) in tables {
            let tid = it.types.resolve(Some(&fqn), module.as_deref());
            let Some(tid) = tid else { continue };
            if it.types.types.get(&tid).and_then(|t| jx::str_(t, "module")) != module.as_deref() || !self.schema.is_kind(Some(&fqn), kind) {
                continue;
            }
            let rows = w.rows(&table);
            if !rows.is_empty() {
                let row = rows[idx.min(rows.len() - 1)].clone();
                let mut ef = |t: &str, raw: &Value| -> Value {
                    match it.enum_value(t, raw) {
                        Ok(v) => v,
                        Err(e) => {
                            pending = Some(e);
                            Value::Unknown
                        }
                    }
                };
                result = Some(w.row_to_obj(&fqn, &row, module.as_deref(), &mut ef));
                break;
            }
        }
        it.world = Some(w);
        if let Some(e) = pending {
            return Err(e);
        }
        Ok(result)
    }

    /// ID сущности ссылки; у обёрток — ID вложенного объекта того же вида.
    pub fn entity_id(&mut self, it: &mut Interpreter, ent: &Value, kind: &str, depth: usize) -> R<Value> {
        let Value::Obj(o) = ent else { return Ok(Value::Unknown) };
        if depth > 2 {
            return Ok(Value::Unknown);
        }
        let mut names: Vec<String> = self.schema.id_fields(kind);
        names.push("id".to_string());
        for name in &names {
            let v = o.borrow().fields.get(name).cloned().unwrap_or(Value::Unknown);
            if v.is_unknown() || v.is_null() {
                continue;
            }
            if let Value::Obj(inner) = &v {
                return self.to_string(it, inner);
            }
            return Ok(v);
        }
        let fields: Vec<(String, Value)> = o.borrow().fields.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        for (k, v) in fields {
            if let Value::Obj(vo) = &v {
                if self.schema.is_kind(vo.borrow().ty.as_deref(), kind) || k.to_lowercase().contains(kind) {
                    let r = self.entity_id(it, &v, kind, depth + 1)?;
                    if !r.is_unknown() {
                        return Ok(r);
                    }
                }
            }
        }
        Ok(Value::Unknown)
    }

    /// `toString()` проекта без событий (`TripId` -> `"G1234"`).
    fn to_string(&mut self, it: &mut Interpreter, obj: &Shared<Obj>) -> R<Value> {
        let ty = obj.borrow().ty.clone();
        let tid = it.types.resolve(ty.as_deref(), None);
        let mid = it.types.method_of(tid.as_deref(), "toString", Some(0));
        let Some(mid) = mid.filter(|m| it.ir.contains_key(m)) else { return Ok(Value::Unknown) };
        it.sink.muted += 1;
        let unit = self.index.unit_of(&mid);
        let r = it.run_body(&mid, &Value::Obj(obj.clone()), &[], &unit, &crate::interpreter::why("SKELETON", "to_string"));
        it.sink.muted -= 1;
        let r = r?;
        Ok(if matches!(r, Value::Str(_)) { r } else { Value::Unknown })
    }

    // --- аргументы обработчика -----------------------------------------------------------------------------------------

    pub fn handler_args(
        &mut self,
        it: &mut Interpreter,
        handler: &str,
        params: &Params,
        refs: &IndexMap<String, String>,
        ctx: &ScenarioContext,
    ) -> R<Vec<Value>> {
        let mut ents: IndexMap<String, Option<Value>> = IndexMap::new();
        for (k, v) in refs {
            let e = self.resolve_ref(it, k, v, 0)?;
            ents.insert(k.clone(), e);
        }
        if it.flags.ref_explicit_id {
            self.explicit_id_refs(it, &mut ents, params, refs)?;
        }
        // Последний слой: параметры запросов шагов, на которые ссылается шаг
        for v in refs.values() {
            if let Some((_, n)) = parse_ref(v) {
                if let Some(sp) = self.step_params.get(&n).filter(|p| !p.is_empty()) {
                    let fields: IndexMap<String, Value> = sp.iter().map(|(k, x)| (k.clone(), Value::from_json(x))).collect();
                    ents.entry(format!("#params{n}")).or_insert_with(|| Some(Value::obj(None, fields, true)));
                }
            }
        }
        let user: Option<String> = self.current_user.clone().or_else(|| ctx.account_id.clone());
        let mut out = Vec::new();
        let plist = it.params.get(handler).cloned().unwrap_or_default();
        for p in plist {
            let anns: IndexMap<String, String> = jx::arr(&p, "annotations")
                .iter()
                .map(|a| (jx::str_(a, "name").unwrap_or("").to_string(), jx::str_(a, "args").unwrap_or("").to_string()))
                .collect();
            let ptype = jx::str_(&p, "type");
            if anns.contains_key("RequestBody") {
                out.push(self.build_dto(it, ptype, params, &ents, user.as_deref(), handler)?);
            } else if anns.contains_key("RequestHeader") {
                out.push(Value::Unknown);
            } else {
                let re = Regex::new(r#""([^"]+)""#).unwrap();
                let name = re
                    .captures(anns.get("PathVariable").map(String::as_str).unwrap_or(""))
                    .map(|m| m[1].to_string())
                    .unwrap_or_else(|| jx::str_(&p, "name").unwrap_or("").to_string());
                out.push(self.field_value(it, &name, params, &ents, user.as_deref(), ptype)?);
            }
        }
        Ok(out)
    }

    /// Ссылка `first`/`second_of_step_N` и строковый ID той же сущности в параметрах шага («рейс G9998»): из
    /// результатов шага N берётся сущность с этим ID. Нет такой в результатах — ссылка как была.
    fn saved_kind(&self, step: i64, kind: &str) -> bool {
        self.saved.get(&step).is_some_and(|v| v.iter().any(|(fqn, _)| self.schema.is_kind(Some(fqn), kind)))
    }

    /// R22, как `StepExecutor._prefer_created`: ссылка `first`/`second_of_step_N` без слова позиции в тексте шага, а
    /// запись этого вида создал шаг M < N, и шаг N её не создавал (список, прочитанный после создания), — ссылка на
    /// созданную запись `new_of_step_M` (последний такой M).
    fn prefer_created(&self, step: i64, action: &str, refs: &IndexMap<String, String>) -> IndexMap<String, String> {
        if has_position_word(action) {
            return refs.clone();
        }
        let mut out = refs.clone();
        for (kind, r) in refs {
            let Some((pick, n)) = parse_ref(r) else { continue };
            if pick == "new" {
                continue;
            }
            let made = self.saved.keys().copied().filter(|&k| k < step && self.saved_kind(k, kind)).max();
            if let Some(m) = made {
                if n > m && !self.saved_kind(n, kind) {
                    out.insert(kind.clone(), format!("new_of_step_{m}"));
                }
            }
        }
        out
    }

    fn explicit_id_refs(
        &mut self,
        it: &mut Interpreter,
        ents: &mut IndexMap<String, Option<Value>>,
        params: &Params,
        refs: &IndexMap<String, String>,
    ) -> R<()> {
        for (kind, r) in refs {
            let Some((pick, n)) = parse_ref(r) else { continue };
            if pick == "new" {
                continue;
            }
            let want = self
                .schema
                .id_fields(kind)
                .into_iter()
                .filter(|f| f != "id")
                .find_map(|f| params.get(&f).and_then(Json::as_str).map(str::to_string));
            let Some(want) = want else { continue };
            if let Some(Some(ent)) = ents.get(kind).cloned() {
                if self.entity_id(it, &ent, kind, 0)?.as_str() == Some(want.as_str()) {
                    continue;
                }
            }
            let found = find_kind(&payload(self.results.get(&n).unwrap_or(&Value::Null), it.envelope.as_ref()), kind, 0, &self.schema);
            for e in found {
                if self.entity_id(it, &e, kind, 0)?.as_str() == Some(want.as_str()) {
                    ents.insert(kind.clone(), Some(e));
                    break;
                }
            }
        }
        Ok(())
    }

    fn field_value(
        &mut self,
        it: &mut Interpreter,
        name: &str,
        params: &Params,
        ents: &IndexMap<String, Option<Value>>,
        user: Option<&str>,
        ftype: Option<&str>,
    ) -> R<Value> {
        if let Some(v) = params.get(name).filter(|v| !v.is_null()) {
            return self.typed(it, v, ftype);
        }
        for (kind, ent) in ents {
            if let Some(ent) = ent {
                if self.schema.id_fields(kind).iter().any(|f| f == name) {
                    let v = self.entity_id(it, ent, kind, 0)?;
                    if !v.is_unknown() {
                        return Ok(v);
                    }
                }
            }
        }
        if self.schema.user_fields.iter().any(|f| f == name) && user.is_some_and(|u| !u.is_empty()) {
            return Ok(Value::str(user.unwrap()));
        }
        if name == "id" {
            return Ok(Value::Unknown);
        }
        let mut aliases: Vec<String> = vec![name.to_string()];
        if let Some(b) = self.body_src.get(name).filter(|b| !b.is_empty() && b.as_str() != name) {
            aliases.push(b.clone());
        }
        for alias in &aliases {
            for ent in ents.values() {
                let Some(ent) = ent else { continue };
                // сама сущность, затем вложенные объекты
                let mut layers: Vec<Value> = vec![ent.clone()];
                if let Value::Obj(o) = ent {
                    layers.extend(o.borrow().fields.values().filter(|x| matches!(x, Value::Obj(_))).cloned());
                }
                for layer in layers {
                    let Value::Obj(lo) = &layer else { continue };
                    let v = lo.borrow().fields.get(alias).cloned();
                    let Some(v) = v else { continue };
                    if v.is_unknown() || v.is_null() {
                        continue;
                    }
                    if let (Value::Obj(vo), Some("java.lang.String")) = (&v, ftype) {
                        return self.to_string(it, vo);
                    }
                    return Ok(v);
                }
            }
        }
        Ok(Value::Unknown)
    }

    fn typed(&mut self, it: &mut Interpreter, v: &Json, ftype: Option<&str>) -> R<Value> {
        let val = Value::from_json(v);
        if matches!(ftype, Some("double" | "float" | "java.lang.Double" | "java.lang.Float")) {
            if let Value::Int(i) = val {
                return Ok(Value::Float(i as f64));
            }
        }
        let tid = ftype.filter(|f| !f.is_empty()).and_then(|f| it.types.resolve(Some(f), None));
        if let Some(t) = tid.filter(|t| it.types.is_enum(Some(t))) {
            if matches!(val, Value::Int(_) | Value::Bool(_) | Value::Str(_)) {
                return if matches!(val, Value::Str(_)) { it.enum_value(&t, &val) } else { Ok(Value::Unknown) };
            }
        }
        Ok(val)
    }

    #[allow(clippy::too_many_arguments)]
    fn build_dto(
        &mut self,
        it: &mut Interpreter,
        ftype: Option<&str>,
        params: &Params,
        ents: &IndexMap<String, Option<Value>>,
        user: Option<&str>,
        handler: &str,
    ) -> R<Value> {
        let n = self.index.n.clone();
        let module = n.get(handler).and_then(|x| jx::str_(x, "module")).map(str::to_string);
        let tid = it.types.resolve(ftype, module.as_deref());
        it.jackson_new(ftype, module.as_deref(), handler)?;
        let obj = shared(Obj::new(ftype.map(str::to_string), IndexMap::new(), true));
        let fields = it.types.all_fields(tid.as_deref());
        let names: BTreeSet<String> = fields.iter().filter_map(|f| jx::str_(f, "name").map(str::to_string)).collect();
        let mut defaults: IndexMap<String, Option<Value>> = IndexMap::new();
        let mut own_ids: BTreeSet<String> = BTreeSet::new();
        let mut fresh: BTreeSet<String> = BTreeSet::new();
        let hname = n.get(handler).and_then(|x| jx::str_(x, "name")).unwrap_or("");
        let create_re = Regex::new(r"(?i)^(create|add|register|save|insert|new)").unwrap();
        if self.verb.as_deref() == Some("POST") && create_re.is_match(hname) {
            // Создание через POST: собственный ID новой сущности клиент не присылает (Jackson оставит null).
            let own: Vec<String> = self.schema.known_kinds().into_iter().filter(|k| self.schema.kind_rank(ftype, k) >= 2).cloned().collect();
            let mut cand: Vec<String> = vec!["id".to_string()];
            for k in &own {
                cand.extend(self.schema.id_fields(k));
            }
            own_ids = cand.into_iter().filter(|c| names.contains(c) && !params.contains_key(c)).collect();
            for o in &own_ids {
                defaults.insert(o.clone(), None);
            }
            // Поле, по которому создающий метод ищет дубликат: значения нет в тексте шага, новая сущность создаётся
            let dedupe = self.dedupe_fields(it, handler, ftype);
            for f in fields.iter() {
                let name = jx::str_(f, "name").unwrap_or("");
                if dedupe.iter().any(|d| d == name) && !params.contains_key(name) && !own_ids.contains(name) && jx::str_(f, "type") == Some("java.lang.String") {
                    defaults.insert(name.to_string(), Some(Value::string(format!("m4-new-{name}"))));
                    fresh.insert(name.to_string());
                }
            }
        }
        if self.is_login(handler) {
            // Вход (Spring Security): поля, которых при входе нет по context скелета, — пустые; имя — пассажир context
            for name in &names {
                if self.login_blanks.contains(&norm(name)) {
                    defaults.insert(name.clone(), Some(Value::str("")));
                } else if norm(name) == "username" && self.user_name.is_some() {
                    defaults.insert(name.clone(), Some(Value::str(self.user_name.as_deref().unwrap())));
                }
            }
        }
        let mut unsent: BTreeSet<String> = BTreeSet::new();
        if it.flags.ui_optional_groups {
            // Группа полей, которую UI шлёт только под общим условием (каталог UI): шаг не дал ни поля группы, ни
            // литерала её условия со значением не по умолчанию — полей в запросе нет, у DTO умолчания полей
            for g in &self.body_groups {
                if !group_sent(g, params) {
                    unsent.extend(g.fields.iter().filter(|n| names.contains(n.as_str()) && !params.contains_key(n.as_str())).cloned());
                }
            }
        }
        for f in fields.iter() {
            let name = jx::str_(f, "name").unwrap_or("").to_string();
            if unsent.contains(&name) {
                obj.borrow_mut().fields.insert(name, crate::interpreter::default_value_pub(f));
                continue;
            }
            let u = if own_ids.contains(&name) { None } else { user };
            let mut v = self.field_value(it, &name, params, ents, u, jx::str_(f, "type"))?;
            if v.is_unknown() && name == "id" {
                // DTO того же вида, что сущность ссылки: id — ID этой сущности
                for (kind, ent) in ents {
                    if self.schema.is_known(kind) && self.schema.kind_rank(ftype, kind) >= 2 {
                        if let Some(ent) = ent {
                            v = self.entity_id(it, ent, kind, 0)?;
                            if !v.is_unknown() {
                                break;
                            }
                        }
                    }
                }
            }
            if v.is_unknown() {
                if let Some(w) = self.written.get(&norm(&name)) {
                    // Значение, записанное прежним шагом (имя при регистрации -> вход)
                    v = w.clone();
                }
            }
            if v.is_unknown() {
                if let Some(d) = defaults.get(&name) {
                    v = d.clone().unwrap_or(Value::Null);
                    if fresh.contains(&name) {
                        self.written.insert(norm(&name), v.clone());
                    }
                }
            }
            if !v.is_unknown() {
                obj.borrow_mut().fields.insert(name, v);
            }
        }
        Ok(it.jackson_fill(Value::Obj(obj), module.as_deref()))
    }

    /// Методы проекта, достижимые из обработчика по рёбрам calls скелета (с реализациями интерфейсов);
    /// `remote` — ещё и через межсервисные вызовы (remote_call скелета) в обработчики других сервисов.
    fn reachable(&mut self, handler: &str, remote: Option<&Interpreter>) -> BTreeSet<String> {
        let key = (handler.to_string(), remote.is_some());
        if let Some(r) = self.reach.get(&key) {
            return r.clone();
        }
        if let (Some(it), None) = (remote, &self.remote_of) {
            let mut of: HashMap<String, BTreeSet<String>> = HashMap::new();
            for (cs, hs) in &it.cs_remote {
                if let Some(m) = self.index.n.get(cs).and_then(|n| jx::str_(n, "method")).filter(|m| !m.is_empty()) {
                    of.entry(m.to_string()).or_default().extend(hs.iter().cloned());
                }
            }
            self.remote_of = Some(of);
        }
        let remote_of = if remote.is_some() { self.remote_of.as_ref() } else { None };
        let mut seen: BTreeSet<String> = BTreeSet::from([handler.to_string()]);
        let mut frontier = vec![handler.to_string()];
        for _ in 0..4 {
            let mut next = Vec::new();
            for m in &frontier {
                let mut targets: Vec<String> = self.index.calls.get(m).map(|ts| ts.iter().cloned().collect()).unwrap_or_default();
                if let Some(hs) = remote_of.and_then(|of| of.get(m)) {
                    targets.extend(hs.iter().cloned());
                }
                for t in &targets {
                    let mut xs = vec![t.clone()];
                    if let Some(o) = self.index.over.get(t) {
                        xs.extend(o.iter().cloned());
                    }
                    for x in xs {
                        if seen.insert(x.clone()) {
                            next.push(x);
                        }
                    }
                }
            }
            frontier = next;
        }
        self.reach.insert(key, seen.clone());
        seen
    }

    /// Обработчик входа: из него достижим метод с вызовом `AuthenticationManager.authenticate`.
    fn is_login(&mut self, handler: &str) -> bool {
        let r = self.reachable(handler, None);
        self.login_ids.keys().any(|k| r.contains(k))
    }

    /// Поля DTO, по которым метод, достижимый из обработчика, ищет дубликат. Достижимость — и через межсервисный
    /// вызов: консоль администратора пересылает тело запроса сервису, который ищет дубликат.
    fn dedupe_fields(&mut self, it: &Interpreter, handler: &str, ftype: Option<&str>) -> Vec<String> {
        let key = (handler.to_string(), ftype.map(str::to_string));
        if let Some(d) = self.dedupe.get(&key) {
            return d.clone();
        }
        let mut out: Vec<String> = Vec::new();
        let reach = self.reachable(handler, Some(it));
        for m in &reach {
            let saves: Vec<i64> = self
                .index
                .entities
                .calls_by_method
                .get(m)
                .map(|cs| cs.iter().filter(|c| c.operation == "SAVE").map(|c| c.line).collect())
                .unwrap_or_default();
            let Some(body) = it.ir.get(m) else { continue };
            if saves.is_empty() {
                continue;
            }
            let ptypes: HashMap<&str, Option<&str>> =
                jx::arr(body, "params").iter().map(|p| (jx::str_(p, "name").unwrap_or(""), jx::str_(p, "type"))).collect();
            let mut calls = Vec::new();
            if let Some(b) = jx::get(body, "body") {
                call_exprs(b, &mut calls);
            }
            for call in calls {
                let c_str = jx::str_(call, "call").unwrap_or("");
                let mut rc = None;
                if let Some((_, pos)) = c_str.rsplit_once('@') {
                    if let Some((l, c)) = pos.split_once(':') {
                        if !l.is_empty() && !c.is_empty() && l.chars().all(|x| x.is_ascii_digit()) && c.chars().all(|x| x.is_ascii_digit()) {
                            rc = it.repo_call(m, l.parse().unwrap_or(0), c.parse().unwrap_or(0));
                        }
                    }
                }
                let Some(rc) = rc else { continue };
                if rc.operation != "READ" || !saves.iter().any(|l| *l > rc.line) {
                    continue;
                }
                for a in jx::arr(call, "args") {
                    if !a.is_object() {
                        continue;
                    }
                    let recv = jx::get(a, "recv").filter(|r| json_truthy_obj(r));
                    let getter = jx::str_(a, "callee").unwrap_or("");
                    let a_args_empty = !jx::get(a, "args").is_some_and(|x| x.as_array().is_some_and(|v| !v.is_empty()));
                    let (Some(recv), true) = (recv, getter.starts_with("get") && getter.chars().count() > 3 && a_args_empty) else { continue };
                    if jx::str_(recv, "ref") == Some("param")
                        && simple_name(ptypes.get(jx::str_(recv, "name").unwrap_or("")).copied().flatten(), true) == simple_name(ftype, true)
                    {
                        let rest: Vec<char> = getter.chars().skip(3).collect();
                        let first: String = rest[0].to_lowercase().collect();
                        out.push(first + &rest[1..].iter().collect::<String>());
                    }
                }
            }
        }
        let mut uniq: Vec<String> = Vec::new();
        for o in out {
            if !uniq.contains(&o) {
                uniq.push(o);
            }
        }
        self.dedupe.insert(key, uniq.clone());
        uniq
    }

    /// Строка шага в том виде, в каком значение хранит мир БД: каждая часть (через запятую) заменяется значением строки
    /// таблицы с тем же ключом; из нескольких — то, что встречается в большем числе колонок.
    fn world_string(&self, it: &Interpreter, v: &str) -> String {
        let Some(w) = it.world.as_ref() else { return v.to_string() };
        let mut tables: BTreeSet<&String> = w.table_of.values().collect();
        for c in w.collections_of.values() {
            tables.extend(c.values());
        }
        let mut cols: IndexMap<String, IndexMap<String, BTreeSet<(String, String)>>> = IndexMap::new();
        for t in tables {
            for row in w.rows(t) {
                for (col, x) in row {
                    if let Value::Str(s) = x {
                        if !s.is_empty() {
                            cols.entry(canon(s)).or_default().entry(s.to_string()).or_default().insert((t.clone(), col.clone()));
                        }
                    }
                }
            }
        }
        let parts: Vec<String> = v
            .split(',')
            .map(|part| {
                let mut cands: Vec<(&String, &BTreeSet<(String, String)>)> =
                    cols.get(&canon(part)).map(|m| m.iter().collect()).unwrap_or_default();
                cands.sort_by(|a, b| b.1.len().cmp(&a.1.len()));
                if !cands.is_empty() && (cands.len() == 1 || cands[0].1.len() > cands[1].1.len()) {
                    cands[0].0.clone()
                } else {
                    part.to_string()
                }
            })
            .collect();
        parts.join(",")
    }

    /// ID пользователя из ответа шага входа или `None`, если шаг не вход.
    fn logged_in_user(&self, sink: &Sink, ret: &Value, env: Option<&Envelope>) -> Option<String> {
        let Value::Obj(p) = payload(ret, env) else { return None };
        for m in sink.methods.keys() {
            for name in self.login_ids.get(m).map(Vec::as_slice).unwrap_or(&[]) {
                if let Some(Value::Str(s)) = p.borrow().fields.get(name) {
                    return Some(s.to_string());
                }
            }
        }
        None
    }

    /// Счётчики M4 для отчёта: решения по условиям UNKNOWN.
    pub fn stats(&self) -> IndexMap<String, usize> {
        let mut c: IndexMap<String, usize> = IndexMap::new();
        for us in self.unknowns.values() {
            for u in us {
                let d = jx::str_(u, "decided").unwrap_or("").split(':').next().unwrap_or("").to_string();
                *c.entry(d).or_insert(0) += 1;
            }
        }
        c.sort_keys();
        c
    }
}

fn json_truthy_obj(v: &Json) -> bool {
    crate::interpreter::json_truthy(v)
}

#[allow(dead_code)]
fn _unused() -> R<()> {
    err("")
}

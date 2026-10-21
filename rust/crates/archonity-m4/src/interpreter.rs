//! Интерпретатор IR (`engine/executor/interpreter.py`): условия в трёхзначной логике, вызовы, события исполнения.
//!
//! Идёт по IR тел методов (`data/ir`) и пишет события исполнения. Условие считается по значениям в трёхзначной логике
//! (TRUE, FALSE, UNKNOWN). UNKNOWN: правило успешного пути (плечо, которое кончается отказом, не берём, если шаг не
//! ожидает отказа), иначе исполняются оба плеча. Вызов проектного метода — рекурсивный вход; RestTemplate — вход в
//! обработчик другого сервиса (R3); репозиторий — запрос к базе мира и событие SQL. Лямбда исполняется, только когда её
//! вызывают (R16); `catch` — только при исключении (R15).

use std::collections::{BTreeSet, HashMap};
use std::path::Path;
use std::rc::Rc;

use anyhow::Result;
use archonity_io::entities::RepositoryCall;
use archonity_io::skeleton::Node;
use archonity_io::world::{derived_props, native_query_conds, optional_of, World};
use archonity_io::{jx, SkeletonIndex, TypeIndex};
use archonity_model::flags::{CollectionTables, Constructors, UnresolvedCalls};
use archonity_model::values::*;
use archonity_model::RuleFlags;
use indexmap::IndexMap;
use regex::Regex;
use serde_json::Value as Json;

use crate::envelope::{self, Envelope};
use crate::ir::{load_ir_dir, IrStore};
use crate::library;

pub const MAX_DEPTH: usize = 48;
pub const MAX_LOOP: usize = 40;
pub const MAX_INVOCATIONS: u64 = 60000;

/// Причина решения: `(source_type, rule)`.
pub type Why = (String, String);

pub fn why(a: &str, b: &str) -> Why {
    (a.to_string(), b.to_string())
}

/// Исключение исполнителя: `_Abort` (бюджет вызовов) или ошибка Python (`KeyError` и т.п.).
#[derive(Debug)]
pub enum Exc {
    Abort,
    Err(String),
}

pub type R<T> = Result<T, Exc>;

pub fn err<T>(msg: impl Into<String>) -> R<T> {
    Err(Exc::Err(msg.into()))
}

/// `e["key"]`: `KeyError`, если ключа нет.
pub fn must<'a>(e: &'a Json, key: &str) -> R<&'a Json> {
    match jx::get(e, key) {
        Some(v) => Ok(v),
        None => err(format!("KeyError: {key}")),
    }
}

pub fn has(e: &Json, key: &str) -> bool {
    e.as_object().is_some_and(|o| o.contains_key(key))
}

/// Истинность JSON-значения как в Python.
pub fn json_truthy(v: &Json) -> bool {
    match v {
        Json::Null => false,
        Json::Bool(b) => *b,
        Json::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Json::String(s) => !s.is_empty(),
        Json::Array(a) => !a.is_empty(),
        Json::Object(o) => !o.is_empty(),
    }
}

/// Поле-список или пустой список (`x.get(k) or []`).
pub fn list_of<'a>(e: &'a Json, key: &str) -> &'a [Json] {
    jx::arr(e, key)
}

/// Как f-строка Python форматирует `x.get(k)`: число, строка или `None`.
fn py_opt(e: &Json, key: &str) -> String {
    match jx::get(e, key) {
        None | Some(Json::Null) => "None".to_string(),
        Some(Json::String(s)) => s.clone(),
        Some(Json::Bool(b)) => if *b { "True" } else { "False" }.to_string(),
        Some(other) => other.to_string(),
    }
}

#[derive(Debug, Clone, Default)]
pub struct Completion {
    pub normal: bool,
    pub returns: Vec<Value>,
    pub brk: bool,
    pub cont: bool,
    pub thrown: bool,
}

impl Completion {
    pub fn new() -> Completion {
        Completion { normal: true, ..Completion::default() }
    }

    pub fn union(&self, o: &Completion) -> Completion {
        Completion {
            normal: self.normal || o.normal,
            returns: self.returns.iter().chain(&o.returns).cloned().collect(),
            brk: self.brk || o.brk,
            cont: self.cont || o.cont,
            thrown: self.thrown || o.thrown,
        }
    }
}

#[derive(Clone)]
pub struct Frame {
    pub method: String,
    pub this: Value,
    pub env: IndexMap<String, Value>,
    pub unit: String,
    pub module: String,
    pub owner: Option<String>,
    /// Последнее решение ветки на пути в этом кадре.
    pub why: Why,
}

/// События шага с причиной первого решения.
#[derive(Debug, Default)]
pub struct Sink {
    /// Метод -> (тип источника, правило, через что).
    pub methods: IndexMap<String, (String, String, Option<String>)>,
    pub calls: IndexMap<(String, String), Why>,
    pub remote: IndexMap<(String, String), Why>,
    pub data: IndexMap<(String, String), Why>,
    /// `(relation, source, target, source_type, rule)`.
    pub prunes: Vec<(String, String, String, String, String)>,
    pub unknowns: Vec<Json>,
    pub muted: i32,
}

impl Sink {
    pub fn execute(&mut self, m: &str, w: &Why, via: Option<String>) {
        if self.muted == 0 {
            self.methods.entry(m.to_string()).or_insert_with(|| (w.0.clone(), w.1.clone(), via));
        }
    }

    pub fn edge(&mut self, rel: &str, s: &str, t: &str, w: &Why) {
        if self.muted != 0 {
            return;
        }
        let map = match rel {
            "calls" => &mut self.calls,
            "remote" => &mut self.remote,
            _ => &mut self.data,
        };
        map.entry((s.to_string(), t.to_string())).or_insert_with(|| w.clone());
    }

    pub fn prune(&mut self, rel: &str, s: &str, t: &str, st: &str, rule: &str) {
        if self.muted == 0 {
            self.prunes.push((rel.into(), s.into(), t.into(), st.into(), rule.into()));
        }
    }
}

/// Снимок поля или списка в журнале плеч.
#[derive(Clone)]
enum Snap {
    Missing,
    Val(Value),
    List(Vec<Value>, bool),
}

#[derive(Clone)]
enum JObj {
    Obj(Shared<Obj>),
    Enum(Shared<EnumV>),
    List(Shared<ListV>),
}

#[derive(Clone)]
struct JEntry {
    obj: JObj,
    field: String,
    old: Snap,
}

type Journal = IndexMap<(usize, String), JEntry>;

fn is_list_field(f: &str) -> bool {
    f == "#list"
}

fn current(o: &JObj, f: &str) -> Snap {
    match o {
        JObj::List(l) => {
            let l = l.borrow();
            Snap::List(l.items.clone(), l.exact)
        }
        JObj::Obj(x) => x.borrow().fields.get(f).cloned().map(Snap::Val).unwrap_or(Snap::Missing),
        JObj::Enum(x) => x.borrow().fields.get(f).cloned().map(Snap::Val).unwrap_or(Snap::Missing),
    }
}

fn restore(o: &JObj, f: &str, old: &Snap) {
    match (o, old) {
        (JObj::List(l), Snap::List(items, exact)) => {
            let mut l = l.borrow_mut();
            l.items = items.clone();
            l.exact = *exact;
        }
        (JObj::Obj(x), Snap::Missing) => {
            x.borrow_mut().fields.shift_remove(f);
        }
        (JObj::Obj(x), Snap::Val(v)) => {
            x.borrow_mut().fields.insert(f.to_string(), v.clone());
        }
        (JObj::Enum(x), Snap::Missing) => {
            x.borrow_mut().fields.shift_remove(f);
        }
        (JObj::Enum(x), Snap::Val(v)) => {
            x.borrow_mut().fields.insert(f.to_string(), v.clone());
        }
        _ => {}
    }
}

pub struct Interpreter {
    pub index: Rc<SkeletonIndex>,
    pub flags: RuleFlags,
    pub n: Rc<IndexMap<String, Node>>,
    pub types: Rc<TypeIndex>,
    pub ir: IrStore,
    pub envelope: Option<Envelope>,
    pub cs_calls: HashMap<String, BTreeSet<String>>,
    pub cs_dispatch: HashMap<String, BTreeSet<String>>,
    pub cs_remote: HashMap<String, BTreeSet<String>>,
    pub cs_data: HashMap<String, BTreeSet<String>>,
    pub cs_delivery: HashMap<String, BTreeSet<String>>,
    templates: HashMap<String, Vec<(Option<String>, Vec<String>)>>,
    pub params: HashMap<String, Vec<Node>>,
    repo_calls: HashMap<(String, i64, i64), RepositoryCall>,
    pub world: Option<World>,
    pub sink: Sink,
    pub expected: String,
    beans: HashMap<String, Shared<Obj>>,
    enum_cache: HashMap<(String, String), Value>,
    pub depth: usize,
    pub invocations: u64,
    stack: Vec<String>,
    pub step: Option<i64>,
    journal: Vec<Journal>,
    journal_start: Vec<u64>,
    lit_cache: HashMap<usize, Value>,
}

const LOG_LEVELS: [&str; 3] = ["info", "warn", "error"];

impl Interpreter {
    pub fn new(index: Rc<SkeletonIndex>, flags: RuleFlags, ir_dir: &Path, targets_root: Option<&Path>) -> Result<Interpreter> {
        let n = index.n.clone();
        let types = Rc::new(TypeIndex::new(n.clone(), &index.edges, targets_root));
        let ir = load_ir_dir(ir_dir)?;
        let envelope = envelope::derive(&index, &ir, targets_root);
        let mut cs_calls: HashMap<String, BTreeSet<String>> = HashMap::new();
        let mut cs_dispatch = HashMap::new();
        let mut cs_remote = HashMap::new();
        let mut cs_data = HashMap::new();
        let mut cs_delivery = HashMap::new();
        for e in index.edges.iter() {
            let src = jx::str_(e, "source").unwrap_or("");
            if !src.starts_with("call:") {
                continue;
            }
            let b: &mut HashMap<String, BTreeSet<String>> = match jx::str_(e, "type") {
                Some("calls") => &mut cs_calls,
                Some("runtime_dispatch") => &mut cs_dispatch,
                Some("remote_call") => &mut cs_remote,
                Some("data_access") => &mut cs_data,
                Some("message_delivery") => &mut cs_delivery,
                _ => continue,
            };
            b.entry(src.to_string()).or_default().insert(jx::str_(e, "target").unwrap_or("").to_string());
        }
        let mut templates: HashMap<String, Vec<(Option<String>, Vec<String>)>> = HashMap::new();
        for (nid, verb, segs) in &index.handlers {
            templates.entry(nid.clone()).or_default().push((verb.clone(), segs.clone()));
        }
        let mut params: HashMap<String, Vec<Node>> = HashMap::new();
        for node in n.values() {
            if jx::str_(node, "kind") == Some("parameter") {
                params.entry(jx::str_(node, "method").unwrap_or("").to_string()).or_default().push(node.clone());
            }
        }
        for v in params.values_mut() {
            v.sort_by_key(|p| jx::int(p, "index").unwrap_or(0));
        }
        let mut repo_calls = HashMap::new();
        for (m, calls) in &index.entities.calls_by_method {
            for c in calls {
                repo_calls.insert((m.clone(), c.line, c.col), c.clone());
            }
        }
        Ok(Interpreter {
            index,
            flags,
            n,
            types,
            ir,
            envelope,
            cs_calls,
            cs_dispatch,
            cs_remote,
            cs_data,
            cs_delivery,
            templates,
            params,
            repo_calls,
            world: None,
            sink: Sink::default(),
            expected: "success".to_string(),
            beans: HashMap::new(),
            enum_cache: HashMap::new(),
            depth: 0,
            invocations: 0,
            stack: Vec::new(),
            step: None,
            journal: Vec::new(),
            journal_start: Vec::new(),
            lit_cache: HashMap::new(),
        })
    }

    /// Факты вызова репозитория по `(метод, строка, колонка)`.
    pub fn repo_call(&self, m: &str, line: i64, col: i64) -> Option<&RepositoryCall> {
        self.repo_calls.get(&(m.to_string(), line, col))
    }

    // --- сценарий и шаг -----------------------------------------------------------------------------------------------

    pub fn begin_scenario(&mut self, db: archonity_io::DatabaseState) {
        self.world = Some(World::new(db, self.types.clone(), self.index.entities.raw_entities()));
        self.beans = HashMap::new();
    }

    /// Шаг: вход обработчика. `args` строится уже в sink шага (разбор тела запроса исполняет конструктор DTO).
    /// `_Abort` ловится здесь (результат `Unknown`), остальные исключения уходят вызывающему, как в Python.
    pub fn run_handler(
        &mut self,
        handler: &str,
        args: &mut dyn FnMut(&mut Interpreter) -> R<Vec<Value>>,
        expected: &str,
        step: Option<i64>,
    ) -> R<(Sink, Value)> {
        self.sink = Sink::default();
        self.expected = if expected.is_empty() { "success".to_string() } else { expected.to_string() };
        self.step = step;
        self.invocations = 0;
        self.depth = 0;
        self.stack = Vec::new();
        self.sink.execute(handler, &why("SKELETON", "ENTRY"), None);
        let unit = self.index.unit_of(handler);
        let r = match args(self) {
            Ok(a) => self.invoke(handler, &Value::Null, &a, &unit, &why("SKELETON", "ENTRY")),
            Err(e) => Err(e),
        };
        let ret = match r {
            Ok(v) => v,
            Err(Exc::Abort) => {
                eprintln!("M4: шаг {step:?} прерван по бюджету вызовов");
                Value::Unknown
            }
            Err(e) => return Err(e),
        };
        Ok((std::mem::take(&mut self.sink), ret))
    }

    // --- мутации и слияние плеч ---------------------------------------------------------------------------------------

    fn journal_top_start(&self) -> Option<u64> {
        self.journal_start.last().copied()
    }

    /// `obj.fields[name] = val` с записью старого значения в журнал плеча (`set_field`).
    pub fn set_field(&mut self, obj: &Value, name: &str, val: Value) {
        match obj {
            Value::Obj(o) => {
                if let Some(start) = self.journal_top_start() {
                    if o.borrow().uid < start {
                        let key = (Rc::as_ptr(o) as *const u8 as usize, name.to_string());
                        let old = o.borrow().fields.get(name).cloned().map(Snap::Val).unwrap_or(Snap::Missing);
                        let top = self.journal.last_mut().unwrap();
                        top.entry(key).or_insert(JEntry { obj: JObj::Obj(o.clone()), field: name.to_string(), old });
                    }
                }
                o.borrow_mut().fields.insert(name.to_string(), val);
            }
            Value::Enum(o) => {
                if self.journal_top_start().is_some() {
                    let key = (Rc::as_ptr(o) as *const u8 as usize, name.to_string());
                    let old = o.borrow().fields.get(name).cloned().map(Snap::Val).unwrap_or(Snap::Missing);
                    let top = self.journal.last_mut().unwrap();
                    top.entry(key).or_insert(JEntry { obj: JObj::Enum(o.clone()), field: name.to_string(), old });
                }
                o.borrow_mut().fields.insert(name.to_string(), val);
            }
            _ => {}
        }
    }

    pub fn touch_list(&mut self, lst: &Shared<ListV>) {
        if let Some(start) = self.journal_top_start() {
            if lst.borrow().uid < start {
                let key = (Rc::as_ptr(lst) as *const u8 as usize, "#list".to_string());
                let old = current(&JObj::List(lst.clone()), "#list");
                let top = self.journal.last_mut().unwrap();
                top.entry(key).or_insert(JEntry { obj: JObj::List(lst.clone()), field: "#list".to_string(), old });
            }
        }
    }

    /// Исполнение нескольких плеч при неизвестном условии: мутации каждого изолированы, затем слияние.
    pub fn run_arms(&mut self, arms: &[&[Json]], fr: &mut Frame) -> R<Completion> {
        struct Res {
            comp: Completion,
            env: IndexMap<String, Value>,
            new: IndexMap<(usize, String), Snap>,
        }
        let mut results: Vec<Res> = Vec::new();
        let mut touched: IndexMap<(usize, String), JEntry> = IndexMap::new();
        for stmts in arms {
            self.journal.push(Journal::new());
            self.journal_start.push(next_uid());
            let w = fr.why.clone();
            let r = self.arm(stmts, fr, &w);
            let j = self.journal.pop().unwrap();
            self.journal_start.pop();
            let (comp, env) = r?;
            let new: IndexMap<_, _> = j.iter().map(|(k, e)| (k.clone(), current(&e.obj, &e.field))).collect();
            for (k, e) in &j {
                restore(&e.obj, &e.field, &e.old);
                touched.entry(k.clone()).or_insert_with(|| e.clone());
            }
            results.push(Res { comp, env, new });
        }
        let live_idx: Vec<usize> = {
            let l: Vec<usize> = results.iter().enumerate().filter(|(_, r)| r.comp.normal).map(|(i, _)| i).collect();
            if l.is_empty() { (0..results.len()).collect() } else { l }
        };
        for (k, e) in &touched {
            let vals: Vec<Snap> = live_idx.iter().map(|&i| results[i].new.get(k).cloned().unwrap_or_else(|| e.old.clone())).collect();
            if is_list_field(&e.field) {
                let mut items: Vec<Value> = Vec::new();
                let mut exact = true;
                for v in &vals {
                    if let Snap::List(its, ex) = v {
                        exact = exact && *ex;
                        for x in its {
                            if !items.iter().any(|y| ident(x, y)) {
                                items.push(x.clone());
                            }
                        }
                    }
                }
                if vals.iter().any(|v| matches!(v, Snap::List(its, _) if its.len() != items.len())) {
                    exact = false;
                }
                if let JObj::List(l) = &e.obj {
                    self.touch_list(l);
                    let mut lb = l.borrow_mut();
                    lb.items = items;
                    lb.exact = exact;
                }
                continue;
            }
            let mut v = vals[0].clone();
            for x in &vals[1..] {
                v = match (&v, x) {
                    (Snap::Val(a), Snap::Val(b)) => Snap::Val(join(a, b)),
                    _ => Snap::Val(Value::Unknown),
                };
            }
            if let Snap::Val(v) = v {
                let target = match &e.obj {
                    JObj::Obj(o) => Value::Obj(o.clone()),
                    JObj::Enum(o) => Value::Enum(o.clone()),
                    JObj::List(_) => continue,
                };
                self.set_field(&target, &e.field, v);
            }
        }
        let arm_results: Vec<(Completion, IndexMap<String, Value>)> = results.iter().map(|r| (r.comp.clone(), r.env.clone())).collect();
        self.merge_env(fr, &arm_results);
        let mut total = results[0].comp.clone();
        for r in &results[1..] {
            total = total.union(&r.comp);
        }
        Ok(total)
    }

    /// Константа enum по имени или порядковому номеру (значение колонки БД).
    pub fn enum_value(&mut self, type_id: &str, key: &Value) -> R<Value> {
        let consts = self.types.enum_constants(type_id);
        let idx = match key {
            Value::Int(_) | Value::Bool(_) => key.as_int_or_bool(),
            Value::Str(s) if !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()) => s.parse::<i64>().ok(),
            _ => None,
        };
        let name = match idx {
            Some(i) => {
                if i < 0 || (i as usize) >= consts.len() {
                    return Ok(Value::Unknown);
                }
                consts[i as usize].0.clone()
            }
            None => py_str(key),
        };
        self.enum_const(type_id, &name)
    }

    pub fn enum_const(&mut self, type_id: &str, name: &str) -> R<Value> {
        let ck = (type_id.to_string(), name.to_string());
        if let Some(v) = self.enum_cache.get(&ck) {
            return Ok(v.clone());
        }
        let consts = self.types.enum_constants(type_id);
        let idx = consts.iter().position(|(c, _)| c == name);
        let ev = Value::Enum(shared(EnumV {
            ty: self.types.fqn(Some(type_id)).unwrap_or_else(|| type_id.to_string()),
            constant: name.to_string(),
            ordinal: idx.map(|i| i as i64),
            fields: IndexMap::new(),
        }));
        self.enum_cache.insert(ck, ev.clone());
        if let Some(i) = idx {
            let args = consts[i].1.clone();
            let ctor = self.types.methods.get(type_id).and_then(|ms| {
                ms.iter().find(|m| jx::str_(&self.n[*m], "name") == Some("<init>") && jx::arr(&self.n[*m], "params_as_written").len() == args.len())
            });
            if let Some(ctor) = ctor.cloned() {
                if self.ir.contains_key(&ctor) {
                    self.sink.muted += 1;
                    let unit = self.index.unit_of(&ctor);
                    let r = self.run_body(&ctor, &ev, &args, &unit, &why("SKELETON", "enum_init"));
                    self.sink.muted -= 1;
                    r?;
                }
            }
        }
        Ok(ev)
    }

    // --- вызов метода -------------------------------------------------------------------------------------------------

    pub fn bean(&mut self, type_id: Option<&str>) -> Value {
        let key = type_id.filter(|t| !t.is_empty()).unwrap_or("?").to_string();
        if let Some(b) = self.beans.get(&key) {
            return Value::Obj(b.clone());
        }
        let mut fields = IndexMap::new();
        for f in self.types.all_fields(type_id).iter() {
            let ft = jx::str_(f, "type").unwrap_or("");
            let anns: Vec<&str> = jx::arr(f, "annotations").iter().filter_map(|a| jx::str_(a, "name")).collect();
            if anns.contains(&"Autowired") || anns.contains(&"Resource") || ft.ends_with("RestTemplate") || self.types.resolve(Some(ft), None).is_some() {
                let name = jx::str_(f, "name").unwrap_or("").to_string();
                fields.insert(name.clone(), Value::Bean(shared(Bean { ty: Some(ft.to_string()), name })));
            }
        }
        let b = shared(Obj::new(self.types.fqn(type_id), fields, true));
        self.beans.insert(key, b.clone());
        Value::Obj(b)
    }

    pub fn invoke(&mut self, mid: &str, this: &Value, args: &[Value], unit: &str, w: &Why) -> R<Value> {
        let n = self.n.clone();
        let node = n.get(mid);
        let owner = node.and_then(|x| jx::str_(x, "owner"));
        let mut this = this.clone();
        let is_static = node.is_some_and(|x| jx::strs(x, "modifiers").contains(&"static"));
        if this.is_null() && !is_static && !mid.ends_with("#<init>()") && !mid.contains("#<init>(") {
            this = self.bean(owner);
        }
        if !self.ir.contains_key(mid) {
            return Ok(Value::Unknown);
        }
        if self.stack.iter().filter(|m| m.as_str() == mid).count() >= 2 || self.depth >= MAX_DEPTH {
            return Ok(Value::Unknown);
        }
        self.invocations += 1;
        if self.invocations > MAX_INVOCATIONS {
            return Err(Exc::Abort);
        }
        crate::trace(&format!("{}\t{}", self.depth, mid));
        self.run_body(mid, &this, args, unit, w)
    }

    pub fn run_body(&mut self, mid: &str, this: &Value, args: &[Value], unit: &str, w: &Why) -> R<Value> {
        let body = self.ir.get(mid).cloned().ok_or_else(|| Exc::Err(format!("KeyError: {mid}")))?;
        let n = self.n.clone();
        let node = n.get(mid);
        let mut env: IndexMap<String, Value> = IndexMap::new();
        for (i, p) in list_of(&body, "params").iter().enumerate() {
            env.insert(must(p, "name").map(|s| s.as_str().unwrap_or("").to_string())?, args.get(i).cloned().unwrap_or(Value::Unknown));
        }
        let mut fr = Frame {
            method: mid.to_string(),
            this: this.clone(),
            env,
            unit: unit.to_string(),
            module: node.and_then(|x| jx::str_(x, "module")).unwrap_or("").to_string(),
            owner: node.and_then(|x| jx::str_(x, "owner")).map(str::to_string),
            why: w.clone(),
        };
        self.depth += 1;
        self.stack.push(mid.to_string());
        let comp = self.exec_block(list_of(&body, "body"), &mut fr);
        self.depth -= 1;
        self.stack.pop();
        let comp = comp?;
        if comp.returns.is_empty() {
            return Ok(if comp.normal { Value::Null } else { Value::Unknown });
        }
        let mut ret = comp.returns[0].clone();
        for r in &comp.returns[1..] {
            ret = join(&ret, r);
        }
        Ok(ret)
    }

    // --- операторы ----------------------------------------------------------------------------------------------------

    pub fn exec_block(&mut self, stmts: &[Json], fr: &mut Frame) -> R<Completion> {
        let mut comp = Completion::new();
        for s in stmts {
            let c = self.exec_stmt(s, fr)?;
            comp = Completion {
                normal: c.normal,
                returns: comp.returns.iter().chain(&c.returns).cloned().collect(),
                brk: comp.brk || c.brk,
                cont: comp.cont || c.cont,
                thrown: comp.thrown || c.thrown,
            };
            if !c.normal {
                return Ok(comp);
            }
        }
        Ok(comp)
    }

    fn exec_stmt(&mut self, s: &Json, fr: &mut Frame) -> R<Completion> {
        let op = jx::str_(s, "op");
        match op {
            Some("expr") => {
                self.eval(must(s, "expr")?, fr)?;
                Ok(Completion::new())
            }
            Some("assign") => {
                let val = if has(s, "expr") { self.eval(must(s, "expr")?, fr)? } else { Value::Unknown };
                let operator = jx::str_(s, "operator").unwrap_or("=");
                self.assign(must(s, "target")?, operator, val, fr)?;
                Ok(Completion::new())
            }
            Some("return") => {
                let mut val = if has(s, "expr") { self.eval(must(s, "expr")?, fr)? } else { Value::Null };
                let copy = match (self.journal_top_start(), &val) {
                    (Some(start), Value::Obj(o)) if o.borrow().uid < start => {
                        // плечо будет откачено
                        let b = o.borrow();
                        Some(Value::Obj(shared(Obj::new(b.ty.clone(), b.fields.clone(), b.open))))
                    }
                    _ => None,
                };
                if let Some(c) = copy {
                    val = c;
                }
                Ok(Completion { normal: false, returns: vec![val], ..Completion::default() })
            }
            Some("throw") => {
                self.eval(must(s, "expr")?, fr)?;
                Ok(Completion { normal: false, thrown: true, ..Completion::default() })
            }
            Some("if") => self.exec_if(s, fr),
            Some("foreach") => self.exec_foreach(s, fr),
            Some("while" | "do" | "for") => self.exec_loop(s, fr),
            Some("try") => self.exec_try(s, fr),
            Some("switch") => self.exec_switch(s, fr),
            Some("break") => Ok(Completion { normal: false, brk: true, ..Completion::default() }),
            Some("continue") => Ok(Completion { normal: false, cont: true, ..Completion::default() }),
            Some("block") => self.exec_block(list_of(s, "body"), fr),
            _ => Ok(Completion::new()),
        }
    }

    /// Плечо в подкадре с копией окружения; возвращает завершение и окружение подкадра.
    fn arm(&mut self, stmts: &[Json], fr: &Frame, w: &Why) -> R<(Completion, IndexMap<String, Value>)> {
        let mut sub = Frame {
            method: fr.method.clone(),
            this: fr.this.clone(),
            env: fr.env.clone(),
            unit: fr.unit.clone(),
            module: fr.module.clone(),
            owner: fr.owner.clone(),
            why: w.clone(),
        };
        let comp = self.exec_block(stmts, &mut sub)?;
        Ok((comp, sub.env))
    }

    fn exec_if(&mut self, s: &Json, fr: &mut Frame) -> R<Completion> {
        let cond = tri(&self.eval(must(s, "cond")?, fr)?);
        let bid = match jx::get(s, "id") {
            Some(v) => py_json_str(v),
            None => format!("b{}", py_opt(s, "line")),
        };
        let short = short_name(&fr.method).to_string();
        let then_s = list_of(s, "then");
        let else_s = list_of(s, "else");
        if cond != Tri::Unknown {
            let take_then = cond == Tri::True;
            let (arm, skipped) = if take_then { ("then", else_s) } else { ("else", then_s) };
            let w = why("IR_BRANCH", &format!("{short}@{bid}:{arm}"));
            self.prune_arm(skipped, fr, &w);
            let (comp, env) = self.arm(if take_then { then_s } else { else_s }, fr, &w)?;
            fr.env.extend(env);
            return Ok(comp);
        }
        // UNKNOWN: правило успешного пути, иначе оба плеча
        if self.expected != "refused" {
            let tf = arm_fails(then_s, self.envelope.as_ref());
            let ef = arm_fails(else_s, self.envelope.as_ref());
            if tf != ef {
                let arm = if tf { "else" } else { "then" };
                let w = why("DEFAULT_RULE", &format!("success_path:{short}@{bid}:{arm}"));
                self.prune_arm(if tf { then_s } else { else_s }, fr, &w);
                let (comp, env) = self.arm(if tf { else_s } else { then_s }, fr, &w)?;
                fr.env.extend(env);
                self.sink.unknowns.push(serde_json::json!({
                    "method": fr.method, "branch": bid, "line": jx::get(s, "line").cloned().unwrap_or(Json::Null),
                    "decided": format!("success_path:{arm}"),
                }));
                return Ok(comp);
            }
        }
        self.sink.unknowns.push(serde_json::json!({
            "method": fr.method, "branch": bid, "line": jx::get(s, "line").cloned().unwrap_or(Json::Null), "decided": "both",
        }));
        self.run_arms(&[then_s, else_s], fr)
    }

    fn merge_env(&mut self, fr: &mut Frame, arms: &[(Completion, IndexMap<String, Value>)]) {
        let live: Vec<&IndexMap<String, Value>> = arms.iter().filter(|(c, _)| c.normal).map(|(_, e)| e).collect();
        if live.is_empty() {
            return;
        }
        let mut keys: Vec<String> = Vec::new();
        for env in &live {
            for k in env.keys() {
                if !keys.contains(k) {
                    keys.push(k.clone());
                }
            }
        }
        for k in keys {
            let vals: Vec<Value> =
                live.iter().map(|env| env.get(&k).cloned().or_else(|| fr.env.get(&k).cloned()).unwrap_or(Value::Unknown)).collect();
            let mut v = vals[0].clone();
            for x in &vals[1..] {
                v = join(&v, x);
            }
            fr.env.insert(k, v);
        }
    }

    /// Запись в журнал отсева: проектные вызовы в неисполненном плече.
    fn prune_arm(&mut self, stmts: &[Json], fr: &Frame, w: &Why) {
        if self.sink.muted != 0 {
            return;
        }
        let mut calls = Vec::new();
        for s in stmts {
            iter_calls(s, &mut calls);
        }
        for cs in calls {
            if let Some(ts) = self.cs_calls.get(cs).cloned() {
                for t in ts {
                    if !self.n.get(&t).is_some_and(|x| jx::get(x, "abstract").is_some_and(json_truthy)) {
                        self.sink.prune("calls", &fr.method, &t, &w.0, &w.1);
                    }
                }
            }
            if let Some(ts) = self.cs_remote.get(cs).cloned() {
                for t in ts {
                    self.sink.prune("remote", &fr.method, &t, &w.0, &w.1);
                }
            }
            if let Some(ts) = self.cs_data.get(cs).cloned() {
                for t in ts {
                    self.sink.prune("data", &fr.method, &t, &w.0, &w.1);
                }
            }
        }
    }

    fn exec_foreach(&mut self, s: &Json, fr: &mut Frame) -> R<Completion> {
        let it = self.eval(must(s, "iter")?, fr)?;
        let (mut items, exact) = iter_items(&it);
        let var = jx::str_(s, "var").unwrap_or("None").to_string();
        if exact && items.is_empty() {
            let w = why("STATE", &format!("R17:empty:{}@{}", short_name(&fr.method), py_opt(s, "id")));
            self.prune_arm(list_of(s, "body"), fr, &w);
            return Ok(Completion::new());
        }
        if items.is_empty() {
            items = vec![Value::Unknown];
        }
        let mut total = Completion::new();
        let n_items = items.len();
        for item in items.into_iter().take(MAX_LOOP) {
            fr.env.insert(var.clone(), item);
            let comp = self.exec_block(list_of(s, "body"), fr)?;
            total = Completion {
                normal: true,
                returns: total.returns.iter().chain(&comp.returns).cloned().collect(),
                brk: false,
                cont: false,
                thrown: total.thrown || comp.thrown,
            };
            if !comp.returns.is_empty() && !comp.normal && !comp.brk && !comp.cont {
                if exact && n_items == 1 {
                    return Ok(Completion { normal: false, returns: total.returns, brk: false, cont: false, thrown: total.thrown });
                }
                break;
            }
            if comp.brk && !comp.normal && comp.returns.is_empty() {
                break;
            }
        }
        Ok(total)
    }

    fn exec_loop(&mut self, s: &Json, fr: &mut Frame) -> R<Completion> {
        for st in list_of(s, "init") {
            self.exec_stmt(st, fr)?;
        }
        let mut total = Completion::new();
        let mut first = true;
        let is_do = jx::str_(s, "op") == Some("do");
        for _ in 0..MAX_LOOP {
            let unknown;
            if !is_do || !first {
                let c = match jx::get(s, "cond").filter(|c| !c.is_null()) {
                    Some(c) => tri(&self.eval(c, fr)?),
                    None => Tri::True,
                };
                if c == Tri::False {
                    break;
                }
                unknown = c == Tri::Unknown;
            } else {
                unknown = false;
            }
            first = false;
            let comp = self.exec_block(list_of(s, "body"), fr)?;
            total = Completion {
                normal: true,
                returns: total.returns.iter().chain(&comp.returns).cloned().collect(),
                brk: false,
                cont: false,
                thrown: total.thrown || comp.thrown,
            };
            if (comp.brk && !comp.normal) || (!comp.returns.is_empty() && !comp.normal) {
                break;
            }
            for u in list_of(s, "update") {
                self.eval(u, fr)?;
            }
            if unknown {
                break;
            }
        }
        Ok(total)
    }

    fn exec_try(&mut self, s: &Json, fr: &mut Frame) -> R<Completion> {
        for r in list_of(s, "resources") {
            self.exec_stmt(r, fr)?;
        }
        let mut comp = self.exec_block(list_of(s, "body"), fr)?;
        let catches = list_of(s, "catches");
        if comp.thrown && !catches.is_empty() {
            let mut out = Completion { normal: comp.normal && !comp.thrown, returns: comp.returns.clone(), brk: comp.brk, cont: comp.cont, thrown: false };
            for c in catches {
                if let Some(v) = jx::str_(c, "var").filter(|v| !v.is_empty()) {
                    fr.env.insert(v.to_string(), Value::Unknown);
                }
                let b = self.exec_block(list_of(c, "body"), fr)?;
                out = out.union(&b);
            }
            comp = out;
        } else if !catches.is_empty() && self.sink.muted == 0 {
            let w = why("DEFAULT_RULE", &format!("R15:{}@{}:catch", short_name(&fr.method), py_opt(s, "id")));
            for c in catches {
                self.prune_arm(list_of(c, "body"), fr, &w);
            }
        }
        if jx::get(s, "finally").is_some_and(json_truthy) {
            let fin = self.exec_block(list_of(s, "finally"), fr)?;
            if !fin.normal {
                return Ok(fin);
            }
        }
        Ok(comp)
    }

    fn exec_switch(&mut self, s: &Json, fr: &mut Frame) -> R<Completion> {
        let sel = self.eval(must(s, "selector")?, fr)?;
        let cases = list_of(s, "cases");
        if !sel.is_unknown() {
            let mut start: Option<usize> = None;
            'find: for (i, c) in cases.iter().enumerate() {
                for lab in list_of(c, "labels") {
                    let lv = self.case_label(lab, &sel, fr)?;
                    if same_value(&lv, &sel) == Tri::True {
                        start = Some(i);
                        break 'find;
                    }
                }
            }
            if start.is_none() {
                start = cases.iter().position(|c| !jx::get(c, "labels").is_some_and(json_truthy));
            }
            let Some(start) = start else { return Ok(Completion::new()) };
            let mut total = Completion::new();
            for c in &cases[start..] {
                let comp = self.exec_block(list_of(c, "body"), fr)?;
                total = if !total.normal { total.union(&comp) } else { comp.clone() };
                if !comp.normal {
                    return Ok(Completion {
                        normal: comp.returns.is_empty() && comp.brk,
                        returns: comp.returns,
                        brk: false,
                        cont: comp.cont,
                        thrown: comp.thrown,
                    });
                }
            }
            return Ok(total);
        }
        let mut bodies: Vec<&[Json]> = cases.iter().map(|c| list_of(c, "body")).collect();
        if !cases.iter().any(|c| !jx::get(c, "labels").is_some_and(json_truthy)) {
            bodies.push(&[]);
        }
        let comp = self.run_arms(&bodies, fr)?;
        Ok(Completion { normal: comp.normal || comp.brk, returns: comp.returns, brk: false, cont: comp.cont, thrown: comp.thrown })
    }

    fn case_label(&mut self, lab: &Json, sel: &Value, fr: &mut Frame) -> R<Value> {
        if let (true, Value::Enum(e)) = (has(lab, "name"), sel) {
            let ty = e.borrow().ty.clone();
            let tid = self.types.resolve(Some(&ty), Some(&fr.module));
            return match tid {
                Some(t) => self.enum_const(&t, jx::str_(lab, "name").unwrap_or("")),
                None => Ok(Value::Unknown),
            };
        }
        self.eval(lab, fr)
    }

    // --- присваивание -------------------------------------------------------------------------------------------------

    fn assign(&mut self, target: &Json, operator: &str, val: Value, fr: &mut Frame) -> R<Value> {
        let mut val = val;
        if operator != "=" {
            let cur = self.eval(target, fr)?;
            val = self.binop(&operator[..operator.len() - 1], &cur, &val)?;
        }
        if has(target, "name") {
            let name = jx::str_(target, "name").unwrap_or("");
            if jx::str_(target, "ref") == Some("field") && matches!(fr.this, Value::Obj(_)) && !fr.env.contains_key(name) {
                let this = fr.this.clone();
                self.set_field(&this, name, val.clone());
            } else {
                fr.env.insert(name.to_string(), val.clone());
            }
        } else if has(target, "field") {
            let obj = self.eval(must(target, "of")?, fr)?;
            if matches!(obj, Value::Obj(_) | Value::Enum(_)) {
                self.set_field(&obj, jx::str_(target, "field").unwrap_or(""), val.clone());
            }
        }
        Ok(val)
    }

    // --- выражения ----------------------------------------------------------------------------------------------------

    fn lit(&mut self, e: &Json) -> R<Value> {
        let key = e as *const Json as usize;
        if let Some(v) = self.lit_cache.get(&key) {
            return Ok(v.clone());
        }
        let t = jx::str_(e, "type");
        let raw = must(e, "lit")?;
        let v = if t == Some("null") {
            Value::Null
        } else if matches!(t, Some("double" | "float")) && !raw.is_null() {
            match raw {
                Json::Number(n) => Value::Float(n.as_f64().unwrap_or(f64::NAN)),
                Json::Bool(b) => Value::Float(*b as i64 as f64),
                Json::String(s) => match s.trim().parse::<f64>() {
                    Ok(f) => Value::Float(f),
                    Err(_) => return err("ValueError: float"),
                },
                _ => return err("TypeError: float"),
            }
        } else {
            Value::from_json(raw)
        };
        self.lit_cache.insert(key, v.clone());
        Ok(v)
    }

    pub fn eval(&mut self, e: &Json, fr: &mut Frame) -> R<Value> {
        if !e.is_object() {
            return Ok(Value::Unknown);
        }
        if has(e, "call") && has(e, "callee") {
            return self.eval_call(e, fr);
        }
        if has(e, "new") {
            return self.eval_new(e, fr);
        }
        if has(e, "lit") {
            return self.lit(e);
        }
        if has(e, "name") {
            return self.eval_name(e, fr);
        }
        if has(e, "field") {
            return self.eval_field(e, fr);
        }
        if has(e, "bin") {
            return self.eval_bin(e, fr);
        }
        if has(e, "un") {
            return self.eval_un(e, fr);
        }
        if has(e, "enum") {
            let tid = self.types.resolve(jx::str_(e, "enum"), Some(&fr.module));
            return match tid {
                Some(t) => self.enum_const(&t, must(e, "constant")?.as_str().unwrap_or("")),
                None => Ok(Value::Unknown),
            };
        }
        if has(e, "const") {
            return match jx::get(e, "value") {
                Some(v) => self.eval(v, fr),
                None => Ok(Value::Unknown),
            };
        }
        if has(e, "tern") {
            let c = tri(&self.eval(must(e, "tern")?, fr)?);
            return match c {
                Tri::True => self.eval(must(e, "then")?, fr),
                Tri::False => self.eval(must(e, "else")?, fr),
                Tri::Unknown => {
                    let a = self.eval(must(e, "then")?, fr)?;
                    let b = self.eval(must(e, "else")?, fr)?;
                    Ok(join(&a, &b))
                }
            };
        }
        if has(e, "assign") {
            let v = self.eval(must(e, "expr")?, fr)?;
            return self.assign(must(e, "target")?, jx::str_(e, "assign").unwrap_or("="), v, fr);
        }
        if has(e, "cast") {
            let v = self.eval(must(e, "e")?, fr)?;
            let c = jx::str_(e, "cast").unwrap_or("");
            if matches!(c, "int" | "long") {
                if let Value::Float(f) = v {
                    return Ok(Value::Int(f as i64));
                }
            }
            if matches!(c, "double" | "float") {
                if let Value::Int(i) = v {
                    return Ok(Value::Float(i as f64));
                }
            }
            return Ok(v);
        }
        if has(e, "instanceof") {
            let v = self.eval(must(e, "e")?, fr)?;
            let re = Regex::new(r"<.*>").unwrap();
            let t = re.replace_all(jx::str_(e, "instanceof").unwrap_or(""), "").into_owned();
            let simple = t.rsplit('.').next().unwrap_or("");
            return Ok(match &v {
                Value::Null => Value::Bool(false),
                Value::Obj(o) if o.borrow().ty.as_deref().is_some_and(|t| !t.is_empty()) => {
                    let b = o.borrow();
                    let ty = b.ty.as_deref().unwrap_or("");
                    if ty.rsplit('.').next().unwrap_or("").rsplit('$').next().unwrap_or("") == simple {
                        Value::Bool(true)
                    } else {
                        Value::Unknown
                    }
                }
                _ => Value::Unknown,
            });
        }
        if has(e, "lambda") {
            let lam = match jx::get(e, "lambda") {
                Some(l) if l.is_object() => l,
                _ => e,
            };
            let params: Vec<String> = list_of(lam, "params")
                .iter()
                .map(|p| match p {
                    Json::String(s) => s.clone(),
                    other => jx::str_(other, "name").unwrap_or("").to_string(),
                })
                .collect();
            return Ok(Value::Lambda(shared(Lambda {
                params,
                body: Rc::new(list_of(lam, "body").to_vec()),
                env: fr.env.clone(),
                this: fr.this.clone(),
                method: fr.method.clone(),
                line: jx::int(lam, "line").unwrap_or(0),
            })));
        }
        if has(e, "method_ref") {
            let cs = jx::str_(e, "call").filter(|c| !c.is_empty());
            let tgt = cs.and_then(|c| self.cs_calls.get(c)).and_then(|s| s.iter().next().cloned());
            return Ok(Value::MethodRef(shared(MethodRef { target: tgt, call: cs.map(str::to_string) })));
        }
        if has(e, "new_array") {
            let mut items = Vec::new();
            for x in list_of(e, "init") {
                items.push(self.eval(x, fr)?);
            }
            return Ok(Value::list(items, true));
        }
        if has(e, "this") || has(e, "super") {
            return Ok(fr.this.clone());
        }
        if has(e, "class") {
            return Ok(Value::Unknown);
        }
        if has(e, "index") {
            let arr = self.eval(must(e, "of")?, fr)?;
            let i = self.eval(must(e, "index")?, fr)?;
            if let (Value::List(l), Some(i)) = (&arr, i.as_int_or_bool()) {
                let l = l.borrow();
                if l.exact && i >= 0 && (i as usize) < l.items.len() {
                    return Ok(l.items[i as usize].clone());
                }
            }
            return Ok(Value::Unknown);
        }
        Ok(Value::Unknown)
    }

    fn eval_name(&mut self, e: &Json, fr: &mut Frame) -> R<Value> {
        let name = must(e, "name")?.as_str().unwrap_or("");
        let r = jx::str_(e, "ref");
        if matches!(r, Some("local" | "param" | "unknown")) || fr.env.contains_key(name) {
            return Ok(fr.env.get(name).cloned().unwrap_or(Value::Unknown));
        }
        if r == Some("field") {
            let found = match &fr.this {
                Value::Obj(o) => {
                    let b = o.borrow();
                    let v = b.get(name);
                    if !v.is_unknown() || b.fields.contains_key(name) { Some(v) } else { None }
                }
                Value::Enum(o) => {
                    let b = o.borrow();
                    let v = b.get(name);
                    if !v.is_unknown() || b.fields.contains_key(name) { Some(v) } else { None }
                }
                _ => None,
            };
            if let Some(v) = found {
                return Ok(v);
            }
            return Ok(self.static_field(fr.owner.as_deref(), name));
        }
        if r == Some("type") {
            let tid = self.types.resolve_simple(name, Some(&fr.module));
            let fqn = tid.and_then(|t| self.types.fqn(Some(&t))).unwrap_or_else(|| name.to_string());
            return Ok(Value::TypeRef(shared(TypeRef { fqn })));
        }
        Ok(Value::Unknown)
    }

    fn static_field(&self, owner: Option<&str>, name: &str) -> Value {
        if let Some(fs) = self.types.fields.get(owner.unwrap_or("")) {
            for f in fs {
                if jx::str_(f, "name") == Some(name) {
                    if let Some(lit) = jx::get(f, "init_literal").filter(|l| !l.is_null()) {
                        return lit_value(lit);
                    }
                }
            }
        }
        Value::Unknown
    }

    fn eval_field(&mut self, e: &Json, fr: &mut Frame) -> R<Value> {
        let of = self.eval(must(e, "of")?, fr)?;
        let name = must(e, "field")?.as_str().unwrap_or("");
        match &of {
            Value::TypeRef(t) => {
                let fqn = t.borrow().fqn.clone();
                let tid = self.types.resolve(Some(&fqn), Some(&fr.module));
                if let Some(t) = tid.as_deref() {
                    if self.types.is_enum(Some(t)) {
                        return self.enum_const(t, name);
                    }
                    return Ok(self.static_field(Some(t), name));
                }
                let simple = fqn.rsplit('.').next().unwrap_or("");
                if matches!(simple, "HttpMethod" | "HttpStatus" | "MediaType") {
                    return Ok(Value::str(name));
                }
                if simple == "Calendar" {
                    return Ok(library::calendar_field(name));
                }
                Ok(library::jdk_constant(simple, name))
            }
            Value::Obj(o) => Ok(o.borrow().get(name)),
            Value::Enum(o) => Ok(o.borrow().get(name)),
            Value::List(l) if name == "length" => {
                let l = l.borrow();
                Ok(if l.exact { Value::Int(l.items.len() as i64) } else { Value::Unknown })
            }
            _ => Ok(Value::Unknown),
        }
    }

    fn eval_bin(&mut self, e: &Json, fr: &mut Frame) -> R<Value> {
        let op = must(e, "bin")?.as_str().unwrap_or("");
        if op == "&&" {
            let a = tri(&self.eval(must(e, "l")?, fr)?);
            if a == Tri::False {
                return Ok(Value::Bool(false));
            }
            let b = tri(&self.eval(must(e, "r")?, fr)?);
            return Ok(t_and(a, b).value());
        }
        if op == "||" {
            let a = tri(&self.eval(must(e, "l")?, fr)?);
            if a == Tri::True {
                return Ok(Value::Bool(true));
            }
            let b = tri(&self.eval(must(e, "r")?, fr)?);
            return Ok(t_or(a, b).value());
        }
        let a = self.eval(must(e, "l")?, fr)?;
        let b = self.eval(must(e, "r")?, fr)?;
        self.binop(op, &a, &b)
    }

    pub fn binop(&mut self, op: &str, a: &Value, b: &Value) -> R<Value> {
        if op == "==" {
            return Ok(same_value(a, b).value());
        }
        if op == "!=" {
            return Ok(t_not(same_value(a, b)).value());
        }
        let strish = |v: &Value| matches!(v, Value::Str(_) | Value::Concat(_));
        if op == "+" && (strish(a) || strish(b)) {
            return Ok(concat(a, b));
        }
        if let (true, Value::Bool(x), Value::Bool(y)) = (matches!(op, "&" | "|" | "^"), a, b) {
            return Ok(Value::Bool(match op {
                "&" => *x && *y,
                "|" => *x || *y,
                _ => x != y,
            }));
        }
        let (x, y) = (num(a), num(b));
        if x.is_unknown() || y.is_unknown() || matches!(a, Value::Str(_)) || matches!(b, Value::Str(_)) {
            return Ok(Value::Unknown);
        }
        let (Some(x), Some(y)) = (x.as_num(), y.as_num()) else { return Ok(Value::Unknown) };
        Ok(match op {
            "+" => arith(x, y, i64::wrapping_add, |p, q| p + q),
            "-" => arith(x, y, i64::wrapping_sub, |p, q| p - q),
            "*" => arith(x, y, i64::wrapping_mul, |p, q| p * q),
            "/" => {
                if y.eq(Num::Int(0)) {
                    Value::Unknown
                } else {
                    match (x, y) {
                        (Num::Int(p), Num::Int(q)) => Value::Int(floor_div(p, q)),
                        _ => Value::Float(x.f() / y.f()),
                    }
                }
            }
            "%" => {
                if y.eq(Num::Int(0)) {
                    Value::Unknown
                } else {
                    match (x, y) {
                        (Num::Int(p), Num::Int(q)) => Value::Int(p - floor_div(p, q).wrapping_mul(q)),
                        _ => {
                            let (p, q) = (x.f(), y.f());
                            let mut r = p % q;
                            if r != 0.0 && (r < 0.0) != (q < 0.0) {
                                r += q;
                            }
                            Value::Float(r)
                        }
                    }
                }
            }
            "<" => Value::Bool(x.lt(y)),
            "<=" => Value::Bool(x.le(y)),
            ">" => Value::Bool(y.lt(x)),
            ">=" => Value::Bool(y.le(x)),
            _ => Value::Unknown,
        })
    }

    fn eval_un(&mut self, e: &Json, fr: &mut Frame) -> R<Value> {
        let op = must(e, "un")?.as_str().unwrap_or("");
        let v = self.eval(must(e, "e")?, fr)?;
        match op {
            "!" => Ok(t_not(tri(&v)).value()),
            "-" => Ok(match num(&v).as_num() {
                Some(Num::Int(i)) => Value::Int(i.wrapping_neg()),
                Some(Num::Float(f)) => Value::Float(-f),
                None => Value::Unknown,
            }),
            "++pre" | "--pre" | "post++" | "post--" => {
                let nv = match num(&v).as_num() {
                    None => Value::Unknown,
                    Some(n) => {
                        let up = op.contains("++");
                        match n {
                            Num::Int(i) => Value::Int(if up { i.wrapping_add(1) } else { i.wrapping_sub(1) }),
                            Num::Float(f) => Value::Float(if up { f + 1.0 } else { f - 1.0 }),
                        }
                    }
                };
                self.assign(must(e, "e")?, "=", nv.clone(), fr)?;
                Ok(if op.ends_with("pre") { nv } else { v })
            }
            _ => Ok(v),
        }
    }

    fn eval_new(&mut self, e: &Json, fr: &mut Frame) -> R<Value> {
        let mut args = Vec::new();
        for a in list_of(e, "args") {
            args.push(self.eval(a, fr)?);
        }
        let re = Regex::new(r"<.*>").unwrap();
        let written = re.replace_all(must(e, "new")?.as_str().unwrap_or(""), "").into_owned();
        let fqn = jx::str_(e, "fqn").filter(|f| !f.is_empty());
        let tid = fqn.and_then(|f| self.types.resolve(Some(f), Some(&fr.module)));
        let Some(tid) = tid else {
            let lib = library::new_library(self, &written, &args);
            return Ok(lib.unwrap_or(Value::Unknown));
        };
        let mut fields = IndexMap::new();
        for f in self.types.all_fields(Some(&tid)).iter() {
            fields.insert(jx::str_(f, "name").unwrap_or("").to_string(), default_value(f));
        }
        let obj = shared(Obj::new(fqn.map(str::to_string), fields, false));
        let objv = Value::Obj(obj.clone());
        let cs = jx::str_(e, "call").filter(|c| !c.is_empty());
        let mut ctors: Vec<String> = cs.and_then(|c| self.cs_calls.get(c)).map(|s| s.iter().cloned().collect()).unwrap_or_default();
        if ctors.is_empty() {
            if let Some(t) = jx::str_(e, "target").filter(|t| !t.is_empty()) {
                ctors = vec![t.to_string()];
            }
        }
        let mut ran = false;
        for ctor in ctors {
            if ctor.contains("Exception#<init>") {
                self.sink.prune("calls", &fr.method, &ctor, "DEFAULT_RULE", "exception_ctor");
                continue;
            }
            let n = self.n.clone();
            if !n.contains_key(&ctor) || n.get(&ctor).is_some_and(|x| jx::get(x, "abstract").is_some_and(json_truthy)) {
                continue;
            }
            let ir_call = cs.and_then(|c| self.cs_calls.get(c)).is_none_or(|s| s.is_empty());
            self.record_call(fr, &ctor, ir_call);
            let w = fr.why.clone();
            self.invoke(&ctor, &objv, &args, &fr.unit.clone(), &w)?;
            ran = true;
        }
        if !ran && !args.is_empty() {
            let fs = self.types.all_fields(Some(&tid));
            if fs.len() == args.len() {
                let mut o = obj.borrow_mut();
                for (f, a) in fs.iter().zip(&args) {
                    o.fields.insert(jx::str_(f, "name").unwrap_or("").to_string(), a.clone());
                }
            } else {
                obj.borrow_mut().open = true;
            }
        }
        Ok(objv)
    }

    // --- вызовы -------------------------------------------------------------------------------------------------------

    fn record_call(&mut self, fr: &Frame, target: &str, ir_call: bool) {
        let w = if ir_call { ("IR_CALL".to_string(), format!("R7;{}", fr.why.1)) } else { fr.why.clone() };
        self.sink.edge("calls", &fr.method, target, &w);
        self.sink.execute(target, &w, Some(format!("calls|{}|{}", fr.method, target)));
    }

    pub fn record_call_pub(&mut self, fr: &Frame, target: &str, ir_call: bool) {
        self.record_call(fr, target, ir_call)
    }

    fn eval_call(&mut self, e: &Json, fr: &mut Frame) -> R<Value> {
        let cs = jx::str_(e, "call").filter(|c| !c.is_empty());
        let callee = jx::str_(e, "callee").unwrap_or("");
        let recv_e = jx::get(e, "recv").filter(|r| !r.is_null());
        let recv = match recv_e {
            Some(r) => self.eval(r, fr)?,
            None => Value::Null,
        };
        let mut args = Vec::new();
        for a in list_of(e, "args") {
            args.push(self.eval(a, fr)?);
        }
        self.log_format(e, &args, fr)?;
        if let Some(cs) = cs {
            if self.cs_remote.contains_key(cs) {
                return self.remote_call(fr, cs, callee, &args);
            }
            if self.cs_data.contains_key(cs) {
                return self.repository_call(fr, cs, callee, &recv, &args);
            }
            if self.cs_delivery.contains_key(cs) {
                return self.message_call(fr, cs);
            }
        }
        let mut targets = self.call_targets(fr, cs, &recv);
        let mut ir_target = false;
        if targets.is_empty() {
            if let Some(t) = jx::str_(e, "target").filter(|t| self.n.contains_key(*t)) {
                targets = vec![t.to_string()];
                ir_target = true;
            }
        }
        if !targets.is_empty() {
            let this = match &recv {
                Value::Obj(_) | Value::Enum(_) => recv.clone(),
                _ if recv_e.is_none() => fr.this.clone(),
                _ => Value::Null,
            };
            let mut ret = Value::Null;
            let mut first = true;
            for t in &targets {
                self.record_call(fr, t, ir_target);
                let w = fr.why.clone();
                let r = self.invoke(t, &this, &args, &fr.unit.clone(), &w)?;
                ret = if first { r } else { join(&ret, &r) };
                first = false;
            }
            if ret.is_unknown() && matches!(recv, Value::Obj(_)) {
                return library::call_library(self, fr, callee, &recv, &args, e);
            }
            return Ok(ret);
        }
        library::call_library(self, fr, callee, &recv, &args, e)
    }

    /// Цели проектного вызова (R2): runtime_dispatch, иначе метод и его переопределения (CHA).
    fn call_targets(&mut self, fr: &Frame, cs: Option<&str>, recv: &Value) -> Vec<String> {
        let Some(cs) = cs else { return Vec::new() };
        let mut out: Vec<String> = Vec::new();
        let mut seen: BTreeSet<String> = BTreeSet::new();
        let disp = self.cs_dispatch.get(cs).filter(|d| !d.is_empty()).cloned();
        let calls: Vec<String> = self.cs_calls.get(cs).map(|s| s.iter().cloned().collect()).unwrap_or_default();
        let n = self.n.clone();
        for t in calls {
            let cands: BTreeSet<String> = if let Some(d) = &disp {
                d.clone()
            } else if n.get(&t).is_some_and(|x| jx::get(x, "abstract").is_some_and(json_truthy)) {
                self.index.cha(&t)
            } else {
                let mut c = self.index.cha(&t);
                c.insert(t.clone());
                c
            };
            for x in cands {
                let node = n.get(&x);
                if node.is_some_and(|nn| jx::get(nn, "abstract").is_some_and(json_truthy)) {
                    continue;
                }
                let module = self.index.module.get(&x).cloned().flatten().unwrap_or_default();
                let in_unit = self.index.units.get(&module).is_some_and(|u| u.contains(&fr.unit));
                if !in_unit {
                    self.sink.prune("calls", &fr.method, &x, "SKELETON", "cross_unit");
                    continue;
                }
                if x.contains("Exception#<init>") {
                    self.sink.prune("calls", &fr.method, &x, "DEFAULT_RULE", "exception_ctor");
                    continue;
                }
                if seen.insert(x.clone()) {
                    out.push(x);
                }
            }
        }
        // Тип получателя известен: оставляем реализацию его класса (R2)
        if out.len() > 1 {
            if let Value::Obj(o) = recv {
                let ty = o.borrow().ty.clone();
                if let Some(ty) = ty.filter(|t| !t.is_empty()) {
                    let tid = self.types.resolve(Some(&ty), Some(&fr.module));
                    let mut chain: BTreeSet<String> = BTreeSet::new();
                    let mut t = tid;
                    while let Some(cur) = t {
                        if !chain.insert(cur.clone()) {
                            break;
                        }
                        t = self.types.super_of.get(&cur).cloned();
                    }
                    let narrowed: Vec<String> =
                        out.iter().filter(|x| jx::str_(&n[x.as_str()], "owner").is_some_and(|o| chain.contains(o))).cloned().collect();
                    if !narrowed.is_empty() {
                        for x in &out {
                            if !narrowed.contains(x) {
                                self.sink.prune("calls", &fr.method, x, "STATE", "receiver_type");
                            }
                        }
                        out = narrowed;
                    }
                }
            }
        }
        out
    }

    // --- удалённые вызовы (RestTemplate, R3) -------------------------------------------------------------------------

    fn remote_call(&mut self, fr: &mut Frame, cs: &str, callee: &str, args: &[Value]) -> R<Value> {
        let url = args.first().cloned().unwrap_or(Value::Unknown);
        let mut verb: Option<String> = match callee {
            "getForObject" | "getForEntity" => Some("GET".into()),
            "postForObject" | "postForEntity" => Some("POST".into()),
            "put" => Some("PUT".into()),
            "delete" => Some("DELETE".into()),
            _ => None,
        };
        let mut body = Value::Unknown;
        if callee == "exchange" && args.len() >= 3 {
            verb = args[1].as_str().map(str::to_string);
            body = match &args[2] {
                Value::Wrapper(w) => w.borrow().body.clone(),
                _ => Value::Unknown,
            };
        } else if matches!(callee, "postForObject" | "postForEntity" | "put") && args.len() >= 2 {
            body = match &args[1] {
                Value::Wrapper(w) => w.borrow().body.clone(),
                other => other.clone(),
            };
        }
        let cands: Vec<String> = self.cs_remote.get(cs).map(|s| s.iter().cloned().collect()).unwrap_or_default();
        let chosen = self.select_handlers(&cands, &url, verb.as_deref());
        let tail = cs.rsplit('@').next().unwrap_or("");
        let mut rets: Vec<Value> = Vec::new();
        for (h, binding) in &chosen {
            let w = if chosen.len() == cands.len() { fr.why.clone() } else { why("IR_BRANCH", &format!("R3:url_dispatch@{tail}")) };
            self.sink.edge("remote", &fr.method, h, &w);
            self.sink.execute(h, &w, Some(format!("remote|{}|{}", fr.method, h)));
            let hargs = self.bind_handler(h, &body, binding)?;
            let unit = self.index.unit_of(h);
            rets.push(self.invoke(h, &Value::Null, &hargs, &unit, &w)?);
        }
        for h in &cands {
            if !chosen.iter().any(|(c, _)| c == h) {
                self.sink.prune("remote", &fr.method, h, "IR_BRANCH", &format!("R3:url_dispatch@{tail}"));
            }
        }
        if rets.is_empty() {
            return Ok(Value::wrapper(Value::Unknown, "response"));
        }
        let mut ret = rets[0].clone();
        for r in &rets[1..] {
            ret = join(&ret, r);
        }
        Ok(if matches!(ret, Value::Wrapper(_)) { ret } else { Value::wrapper(ret, "response") })
    }

    fn select_handlers(&self, cands: &[String], url: &Value, verb: Option<&str>) -> Vec<(String, IndexMap<String, Value>)> {
        let text: Option<String> = match url {
            Value::Str(s) => Some(s.to_string()),
            Value::Concat(c) => Some(c.borrow().render("\0")),
            _ => None,
        };
        let all = |cs: &[String]| cs.iter().map(|h| (h.clone(), IndexMap::new())).collect::<Vec<_>>();
        let Some(text) = text else { return all(cands) };
        let mut host: Option<String> = None;
        let mut path = text.clone();
        let re = Regex::new(r"^https?://([^/:\x00]+)(?::\d+)?(/.*)?$").unwrap();
        if let Some(m) = re.captures(&text) {
            host = Some(m[1].to_string());
            path = m.get(2).map(|g| g.as_str().to_string()).unwrap_or_else(|| "/".to_string());
        }
        let mut query = String::new();
        if let Some((p, q)) = path.split_once('?') {
            query = q.to_string();
            path = p.to_string();
        }
        let segs: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
        let mut out: Vec<(String, IndexMap<String, Value>, usize)> = Vec::new();
        for h in cands {
            let module = self.n.get(h).and_then(|x| jx::str_(x, "module")).unwrap_or("");
            if let Some(hh) = &host {
                if !hh.contains('\0') && hh != module {
                    continue;
                }
            }
            for (tverb, tpl) in self.templates.get(h).map(Vec::as_slice).unwrap_or(&[]) {
                if let (Some(v), Some(tv)) = (verb, tverb) {
                    if !v.is_empty() && v != tv {
                        continue;
                    }
                }
                if let Some(mut b) = match_template(&segs, tpl) {
                    let holes = tpl.iter().enumerate().filter(|(i, t)| *i < segs.len() && segs[*i].contains('\0') && !t.starts_with('{')).count();
                    if !query.is_empty() {
                        for kv in query.split('&') {
                            if let Some((k, v)) = kv.split_once('=') {
                                b.insert(k.to_string(), if v.contains('\0') { Value::Unknown } else { Value::str(v) });
                            }
                        }
                    }
                    out.push((h.clone(), b, holes));
                    break;
                }
            }
        }
        if out.is_empty() {
            return all(cands);
        }
        let best = out.iter().map(|(_, _, r)| *r).min().unwrap();
        out.into_iter().filter(|(_, _, r)| *r == best).map(|(h, b, _)| (h, b)).collect()
    }

    fn bind_handler(&mut self, h: &str, body: &Value, binding: &IndexMap<String, Value>) -> R<Vec<Value>> {
        let mut out = Vec::new();
        let params = self.params.get(h).cloned().unwrap_or_default();
        let hnode_module = self.n.get(h).and_then(|x| jx::str_(x, "module")).map(str::to_string);
        for p in params {
            let anns: IndexMap<String, String> = jx::arr(&p, "annotations")
                .iter()
                .map(|a| (jx::str_(a, "name").unwrap_or("").to_string(), jx::str_(a, "args").unwrap_or("").to_string()))
                .collect();
            let name = jx::str_(&p, "name").unwrap_or("");
            if anns.contains_key("RequestBody") {
                self.jackson_new(jx::str_(&p, "type"), hnode_module.as_deref(), h)?;
                let copy = library::json_copy(body, jx::str_(&p, "type"));
                out.push(self.jackson_fill(copy, hnode_module.as_deref()));
            } else if let Some(a) = anns.get("PathVariable") {
                let re = Regex::new(r#""([^"]+)""#).unwrap();
                let key = re.captures(a).map(|m| m[1].to_string()).unwrap_or_else(|| name.to_string());
                out.push(binding.get(&key).cloned().unwrap_or(Value::Unknown));
            } else if anns.contains_key("RequestHeader") {
                out.push(Value::Unknown);
            } else {
                out.push(binding.get(name).cloned().unwrap_or(Value::Unknown));
            }
        }
        Ok(out)
    }

    /// Jackson создаёт тело запроса конструктором без аргументов (R7, ADR-006): исполняется только рукописный конструктор.
    pub fn jackson_new(&mut self, ftype: Option<&str>, module: Option<&str>, handler: &str) -> R<()> {
        if !self.flags.jackson_ctor {
            return Ok(());
        }
        let tid = ftype.filter(|f| !f.is_empty()).and_then(|f| self.types.resolve(Some(f), module));
        let Some(tid) = tid else { return Ok(()) };
        let n = self.n.clone();
        let ctor = self.types.methods.get(&tid).and_then(|ms| {
            ms.iter().find(|m| jx::str_(&n[*m], "name") == Some("<init>") && jx::arr(&n[*m], "params_as_written").is_empty()).cloned()
        });
        let Some(ctor) = ctor.filter(|c| self.ir.contains_key(c)) else { return Ok(()) };
        let w = why("FRAMEWORK_RULE", "R7:jackson_ctor");
        self.sink.execute(&ctor, &w, Some(format!("jackson|{handler}|{ctor}")));
        let mut fields = IndexMap::new();
        for f in self.types.all_fields(Some(&tid)).iter() {
            fields.insert(jx::str_(f, "name").unwrap_or("").to_string(), default_value(f));
        }
        let obj = Value::obj(self.types.fqn(Some(&tid)).as_deref(), fields, false);
        let unit = self.index.unit_of(&ctor);
        self.invoke(&ctor, &obj, &[], &unit, &w)?;
        Ok(())
    }

    // --- Lombok-toString при логировании (R5) -------------------------------------------------------------------------

    fn is_logger(&self, recv_e: Option<&Json>, fr: &Frame) -> bool {
        let Some(r) = recv_e else { return false };
        let (name, owner): (String, Option<String>);
        if jx::str_(r, "ref") == Some("field") && jx::str_(r, "name").is_some_and(|n| !n.is_empty()) {
            name = jx::str_(r, "name").unwrap_or("").to_string();
            owner = self.n.get(&fr.method).and_then(|x| jx::str_(x, "owner")).map(str::to_string);
        } else if jx::get(r, "field").is_some_and(json_truthy) && jx::get(r, "of").and_then(|o| jx::str_(o, "ref")) == Some("type") {
            let cls = jx::get(r, "of").and_then(|o| jx::str_(o, "name"));
            name = jx::str_(r, "field").unwrap_or("").to_string();
            owner = self
                .types
                .resolve(cls, Some(&fr.module))
                .or_else(|| cls.and_then(|c| self.types.resolve_simple(c, Some(&fr.module))));
        } else {
            return false;
        }
        self.types
            .fields
            .get(owner.as_deref().unwrap_or(""))
            .is_some_and(|fs| fs.iter().any(|f| jx::str_(f, "name") == Some(name.as_str()) && jx::str_(f, "type").unwrap_or("").ends_with("Logger")))
    }

    fn log_format(&mut self, e: &Json, args: &[Value], fr: &Frame) -> R<()> {
        let raw = list_of(e, "args");
        if !self.flags.lombok_tostring || !LOG_LEVELS.contains(&jx::str_(e, "callee").unwrap_or("")) || raw.is_empty() {
            return Ok(());
        }
        let first_lit = jx::get(&raw[0], "lit").filter(|l| json_truthy(l)).map(py_json_str).unwrap_or_default();
        if !first_lit.contains("{}") || !self.is_logger(jx::get(e, "recv").filter(|r| !r.is_null()), fr) {
            return Ok(());
        }
        let mut seen = BTreeSet::new();
        for v in args.iter().skip(1) {
            self.lombok_tostring(v, fr, &mut seen, 0)?;
        }
        Ok(())
    }

    fn lombok_tostring(&mut self, v: &Value, fr: &Frame, seen: &mut BTreeSet<usize>, depth: usize) -> R<()> {
        if depth > 4 {
            return Ok(());
        }
        if let Some(a) = v.addr() {
            if !seen.insert(a) {
                return Ok(());
            }
        }
        match v {
            Value::List(l) => {
                let items = l.borrow().items.clone();
                for x in &items {
                    self.lombok_tostring(x, fr, seen, depth + 1)?;
                }
                return Ok(());
            }
            Value::Map(m) => {
                let vals: Vec<Value> = m.borrow().data.values().map(|(_, v)| v.clone()).collect();
                for x in &vals {
                    self.lombok_tostring(x, fr, seen, depth + 1)?;
                }
                return Ok(());
            }
            _ => {}
        }
        let Value::Obj(o) = v else { return Ok(()) };
        let ty = o.borrow().ty.clone();
        let Some(ty) = ty.filter(|t| !t.is_empty()) else { return Ok(()) };
        let Some(tid) = self.types.resolve(Some(&ty), Some(&fr.module)) else { return Ok(()) };
        let w = why("FRAMEWORK_RULE", "R5:lombok_tostring");
        let n = self.n.clone();
        let mut own: IndexMap<String, String> = IndexMap::new();
        for m in self.types.methods.get(&tid).cloned().unwrap_or_default() {
            if jx::arr(&n[&m], "params_as_written").is_empty() {
                own.insert(jx::str_(&n[&m], "name").unwrap_or("").to_string(), m);
            }
        }
        if let Some(m) = own.get("toString").cloned() {
            if self.ir.contains_key(&m) {
                self.sink.execute(&m, &w, Some(format!("tostring|{}|{}", fr.method, m)));
                let unit = self.index.unit_of(&m);
                self.invoke(&m, v, &[], &unit, &w)?;
            }
            return Ok(());
        }
        let anns: BTreeSet<&str> =
            self.types.types.get(&tid).map(|t| jx::arr(t, "annotations").iter().filter_map(|a| jx::str_(a, "name")).collect()).unwrap_or_default();
        if !["Data", "ToString", "Value"].iter().any(|a| anns.contains(a)) {
            return Ok(());
        }
        let fields: Vec<Node> = self.types.fields.get(&tid).cloned().unwrap_or_default();
        for f in fields {
            if jx::strs(&f, "modifiers").contains(&"static") {
                continue;
            }
            let name = jx::str_(&f, "name").unwrap_or("");
            let cap = envelope::upper_first(name);
            let mut getter = if jx::str_(&f, "type") == Some("boolean") { own.get(&format!("is{cap}")).cloned() } else { None };
            if getter.is_none() {
                getter = own.get(&format!("get{cap}")).cloned();
            }
            let mut val = o.borrow().fields.get(name).cloned().unwrap_or(Value::Unknown);
            if let Some(g) = getter.filter(|g| self.ir.contains_key(g)) {
                self.sink.execute(&g, &w, Some(format!("tostring|{}|{}", fr.method, g)));
                let unit = self.index.unit_of(&g);
                let r = self.invoke(&g, v, &[], &unit, &w)?;
                if !r.is_unknown() {
                    val = r;
                }
            }
            self.lombok_tostring(&val, fr, seen, depth + 1)?;
        }
        Ok(())
    }

    /// Jackson заполняет DTO через сеттеры: рукописный сеттер исполняется (без событий: вызов идёт через отражение).
    pub fn jackson_fill(&mut self, obj: Value, module: Option<&str>) -> Value {
        let Value::Obj(o) = &obj else { return obj };
        let ty = o.borrow().ty.clone();
        let Some(ty) = ty.filter(|t| !t.is_empty()) else { return obj };
        let Some(tid) = self.types.resolve(Some(&ty), module) else { return obj };
        let fields: Vec<(String, Value)> = o.borrow().fields.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        for (name, v) in fields {
            if v.is_unknown() {
                continue;
            }
            let setter = self.types.method_of(Some(&tid), &format!("set{}", envelope::upper_first(&name)), Some(1));
            if let Some(setter) = setter.filter(|s| self.ir.contains_key(s)) {
                self.sink.muted += 1;
                let unit = self.index.unit_of(&setter);
                let r = self.run_body(&setter, &obj, &[v.clone()], &unit, &why("SKELETON", "jackson_setter"));
                self.sink.muted -= 1;
                if r.is_err() {
                    o.borrow_mut().fields.insert(name, v);
                }
            }
        }
        obj
    }

    fn message_call(&mut self, fr: &mut Frame, cs: &str) -> R<Value> {
        let targets: Vec<String> = self.cs_delivery.get(cs).map(|s| s.iter().cloned().collect()).unwrap_or_default();
        if !self.flags.rabbitmq_delivery {
            for t in &targets {
                self.sink.prune("remote", &fr.method, t, "DEFAULT_RULE", "ablate_rabbitmq_delivery");
            }
            return Ok(Value::Null);
        }
        for t in targets {
            let w = fr.why.clone();
            self.sink.edge("remote", &fr.method, &t, &w);
            self.sink.execute(&t, &w, Some(format!("remote|{}|{}", fr.method, t)));
            let nparams = self.params.get(&t).map(Vec::len).unwrap_or(0);
            let unit = self.index.unit_of(&t);
            self.invoke(&t, &Value::Null, &vec![Value::Unknown; nparams], &unit, &w)?;
        }
        Ok(Value::Null)
    }

    // --- репозитории --------------------------------------------------------------------------------------------------

    fn repository_call(&mut self, fr: &mut Frame, cs: &str, callee: &str, _recv: &Value, args: &[Value]) -> R<Value> {
        let n = self.n.clone();
        let node = n.get(cs);
        let key = (fr.method.clone(), node.and_then(|x| jx::int(x, "line")).unwrap_or(-1), node.and_then(|x| jx::int(x, "col")).unwrap_or(-1));
        let rc = self.repo_calls.get(&key).cloned();
        let repo_m = self.cs_calls.get(cs).and_then(|s| s.iter().next().cloned());
        let repo_node = repo_m.as_deref().and_then(|m| n.get(m)).cloned().unwrap_or(Json::Null);
        let entity = rc.as_ref().and_then(|r| r.entity.as_ref()).map(|e| e.ty.clone());
        let (result, rows) = self.repo_semantics(fr, callee, args, entity.as_deref(), &repo_node)?;
        let tables: Vec<String> = self.cs_data.get(cs).map(|s| s.iter().cloned().collect()).unwrap_or_default();
        for t in tables {
            let (ok, w) = self.data_table_allowed(fr, &t);
            if ok {
                self.sink.edge("data", &fr.method, &t, &w);
            } else {
                self.sink.prune("data", &fr.method, &t, &w.0, &w.1);
            }
        }
        if let Some(rc) = rc {
            self.hydrate(fr, &rc, rows)?;
        }
        Ok(result)
    }

    fn data_table_allowed(&self, fr: &Frame, t: &str) -> (bool, Why) {
        if self.flags.collection_tables_on_read != CollectionTables::All {
            if let Some((ok, reason)) = self.index.entities.collection_table_loaded(&fr.method, t) {
                return (ok, ("STATE".to_string(), reason));
            }
        }
        (true, fr.why.clone())
    }

    /// Результат вызова репозитория и наличие строк (`True`, `False`, `Unknown`) для R7.
    fn repo_semantics(&mut self, fr: &Frame, callee: &str, args: &[Value], entity: Option<&str>, repo_node: &Json) -> R<(Value, Tri)> {
        let ret_t = jx::str_(repo_node, "return").unwrap_or("").to_string();
        let many = ["List", "Set", "Collection", "Iterable"].iter().any(|x| ret_t.contains(x)) || ret_t.ends_with("ArrayList");
        let has_world_entity = entity.is_some_and(|e| self.world.as_ref().is_some_and(|w| w.table_of.contains_key(e)));
        let a0 = args.first().cloned().unwrap_or(Value::Unknown);
        if !has_world_entity {
            if callee.starts_with("save") {
                return Ok((args.first().cloned().unwrap_or(Value::Unknown), Tri::Unknown));
            }
            if many {
                return Ok((Value::list(Vec::new(), false), Tri::Unknown));
            }
            if ret_t.contains("Optional") {
                return Ok((Value::optional(Value::Unknown, false), Tri::Unknown));
            }
            return Ok((Value::Unknown, Tri::Unknown));
        }
        let entity = entity.unwrap();
        let module = fr.module.clone();
        let md = Some(module.as_str());
        let id_field = |it: &Interpreter| it.world.as_ref().unwrap().id_field.get(entity).cloned().unwrap_or_else(|| "id".to_string());
        if matches!(callee, "save" | "saveAndFlush") {
            self.world.as_mut().unwrap().save(entity, &a0, md);
            return Ok((a0, Tri::True));
        }
        if callee == "saveAll" {
            if let Value::List(l) = &a0 {
                let items = l.borrow().items.clone();
                for x in &items {
                    self.world.as_mut().unwrap().save(entity, x, md);
                }
            }
            return Ok((a0, Tri::True));
        }
        if matches!(callee, "deleteById" | "delete" | "deleteAll") {
            let n = if callee == "deleteById" {
                let idf = id_field(self);
                self.world.as_mut().unwrap().delete(entity, &[(idf, a0.clone())], md)
            } else if callee == "delete" && matches!(args.first(), Some(Value::Obj(_))) {
                let idf = id_field(self);
                let idv = match &a0 {
                    Value::Obj(o) => o.borrow().get(&idf),
                    _ => Value::Unknown,
                };
                self.world.as_mut().unwrap().delete(entity, &[(idf, idv)], md)
            } else {
                0
            };
            return Ok((Value::Null, if n > 0 { Tri::True } else { Tri::Unknown }));
        }
        let mut kind = "find".to_string();
        let mut conds: Option<Vec<(String, Value)>>;
        if matches!(callee, "findById" | "getById" | "getOne" | "findOne") {
            conds = Some(vec![(id_field(self), a0.clone())]);
        } else if callee == "findAll" && args.is_empty() {
            conds = Some(Vec::new());
        } else if callee == "findAllById" {
            conds = Some(vec![(id_field(self), a0.clone())]);
        } else {
            let sql = jx::arr(repo_node, "annotations").iter().find(|a| jx::str_(a, "name") == Some("Query")).map(|a| jx::str_(a, "args").unwrap_or("").to_string());
            conds = None;
            if let Some(sql) = sql {
                let text = if sql.contains('\\') { unicode_escape(&sql) } else { sql };
                if let Some(nq) = native_query_conds(&text) {
                    conds = Some(nq.into_iter().map(|(c, i)| (format!("#col:{c}"), args.get(i).cloned().unwrap_or(Value::Unknown))).collect());
                }
            } else if let Some((k, props)) = derived_props(callee) {
                kind = k;
                conds = Some(props.into_iter().enumerate().map(|(i, p)| (p, args.get(i).cloned().unwrap_or(Value::Unknown))).collect());
            }
        }
        let (objs, mut exact) = {
            let w = self.world.take().unwrap();
            let c: &[(String, Value)] = conds.as_deref().unwrap_or(&[]);
            let mut pending: Option<Exc> = None;
            let r = {
                let mut ef = |t: &str, raw: &Value| -> Value {
                    match self.enum_value(t, raw) {
                        Ok(v) => v,
                        Err(e) => {
                            pending = Some(e);
                            Value::Unknown
                        }
                    }
                };
                w.select(entity, c, md, &mut ef)
            };
            self.world = Some(w);
            if let Some(e) = pending {
                return Err(e);
            }
            r
        };
        if conds.is_none() {
            exact = false;
        }
        if kind.starts_with("delete") || kind.starts_with("remove") {
            let n = match &conds {
                Some(c) if !c.is_empty() => self.world.as_mut().unwrap().delete(entity, c, md),
                _ => 0,
            };
            return Ok((Value::Null, if exact { Tri::from_bool(n != 0) } else { Tri::Unknown }));
        }
        let rows = if exact { Tri::from_bool(!objs.is_empty()) } else { Tri::Unknown };
        if kind == "exists" {
            return Ok((if exact { Value::Bool(!objs.is_empty()) } else { Value::Unknown }, rows));
        }
        if kind == "count" {
            return Ok((if exact { Value::Int(objs.len() as i64) } else { Value::Unknown }, rows));
        }
        if many {
            let mut l = ListV::new(objs.iter().map(|o| Value::Obj(o.clone())).collect(), exact);
            l.elem_type = Some(entity.to_string());
            return Ok((Value::List(shared(l)), rows));
        }
        if ret_t.contains("Optional") {
            return Ok((optional_of(&objs, exact, entity), rows));
        }
        if exact {
            return Ok((objs.first().map(|o| Value::Obj(o.clone())).unwrap_or(Value::Null), rows));
        }
        if objs.is_empty() {
            return Ok((Value::Null, rows));
        }
        let obj = if objs.len() == 1 { objs[0].clone() } else { shared(Obj::new(Some(entity.to_string()), IndexMap::new(), true)) };
        obj.borrow_mut().maybe_null = true;
        Ok((Value::Obj(obj), rows))
    }

    /// Конструкторы сущности при загрузке строк Hibernate (R7) и `equals` из `list.contains`.
    fn hydrate(&mut self, fr: &Frame, rc: &RepositoryCall, rows: Tri) -> R<()> {
        let mode = match self.flags.constructors {
            Constructors::CallerOnly => "caller_only",
            Constructors::All => "all",
            Constructors::Off => "off",
        };
        if mode == "off" || rc.ctors.is_empty() {
            return Ok(());
        }
        let allowed = self.index.entities.allowed_ctors(mode);
        let ctors: Vec<&String> = rc.ctors.iter().filter(|c| allowed.as_ref().is_none_or(|a| a.contains(*c))).collect();
        if ctors.is_empty() {
            return Ok(());
        }
        let op = rc.operation.as_str();
        let via = format!("data|{}|{}", fr.method, rc.main_table.clone().unwrap_or_default());
        let rule;
        if op == "SAVE" {
            if !rc.id_assigned.unwrap_or(false) {
                return Ok(());
            }
            rule = format!("R7:save_merge({})", rc.id_assigned_reason.clone().unwrap_or_else(|| "None".to_string()));
        } else if op == "READ" || op == "DELETE" {
            if op == "READ" && rc.expects.as_deref() == Some("EMPTY") {
                return Ok(());
            }
            if rows == Tri::False {
                for c in &ctors {
                    self.sink.prune("executes", "scenario:?", c, "STATE", "R7:read_no_rows(m4)");
                }
                return Ok(());
            }
            rule = format!("R7:{}(m4 rows={})", op.to_lowercase(), if rows == Tri::True { "yes" } else { "unknown" });
        } else {
            return Ok(());
        }
        for c in ctors {
            let w = why("STATE", &rule);
            self.sink.execute(c, &w, Some(via.clone()));
            let ty = rc.entity.as_ref().map(|e| e.ty.as_str());
            let obj = Value::obj(ty, IndexMap::new(), true);
            self.invoke(c, &obj, &[], &fr.unit, &w)?;
        }
        Ok(())
    }

    // --- лямбды -------------------------------------------------------------------------------------------------------

    pub fn call_lambda(&mut self, lam: &Value, args: &[Value], fr: &mut Frame) -> R<Value> {
        match lam {
            Value::MethodRef(m) => {
                let target = m.borrow().target.clone();
                if let Some(t) = target.filter(|t| self.n.contains_key(t)) {
                    self.record_call(fr, &t, false);
                    let recv = match args.first() {
                        Some(a @ Value::Obj(_)) => a.clone(),
                        _ => Value::Null,
                    };
                    let rest: Vec<Value> = if !recv.is_null() { args[1..].to_vec() } else { args.to_vec() };
                    let w = fr.why.clone();
                    return self.invoke(&t, &recv, &rest, &fr.unit.clone(), &w);
                }
                Ok(Value::Unknown)
            }
            Value::Lambda(l) => {
                let (params, body, mut env, this, method) = {
                    let l = l.borrow();
                    (l.params.clone(), l.body.clone(), l.env.clone(), l.this.clone(), l.method.clone())
                };
                for (i, p) in params.iter().enumerate() {
                    env.insert(p.clone(), args.get(i).cloned().unwrap_or(Value::Unknown));
                }
                let mut sub = Frame {
                    method,
                    this,
                    env,
                    unit: fr.unit.clone(),
                    module: fr.module.clone(),
                    owner: fr.owner.clone(),
                    why: fr.why.clone(),
                };
                let comp = self.exec_block(&body, &mut sub)?;
                if comp.returns.is_empty() {
                    return Ok(Value::Null);
                }
                let mut ret = comp.returns[0].clone();
                for r in &comp.returns[1..] {
                    ret = join(&ret, r);
                }
                Ok(ret)
            }
            _ => Ok(Value::Unknown),
        }
    }
}

// --- вспомогательное ------------------------------------------------------------------------------------------------

fn short_name(method: &str) -> &str {
    method.splitn(3, ':').last().unwrap_or("")
}

fn py_json_str(v: &Json) -> String {
    match v {
        Json::String(s) => s.clone(),
        Json::Null => "None".to_string(),
        Json::Bool(b) => if *b { "True" } else { "False" }.to_string(),
        other => other.to_string(),
    }
}

fn arith(x: Num, y: Num, fi: fn(i64, i64) -> i64, ff: fn(f64, f64) -> f64) -> Value {
    match (x, y) {
        (Num::Int(a), Num::Int(b)) => Value::Int(fi(a, b)),
        _ => Value::Float(ff(x.f(), y.f())),
    }
}

fn floor_div(a: i64, b: i64) -> i64 {
    let q = a.wrapping_div(b);
    if a.wrapping_rem(b) != 0 && ((a < 0) != (b < 0)) {
        q - 1
    } else {
        q
    }
}

/// `lit_value`: значение литерала поля из текста исходника.
pub fn lit_value(text: &Json) -> Value {
    let Json::String(s) = text else { return Value::from_json(text) };
    let t = s.trim();
    if t.len() >= 2 && t.starts_with('"') && t.ends_with('"') {
        return Value::str(&t[1..t.len() - 1]);
    }
    if t == "true" || t == "false" {
        return Value::Bool(t == "true");
    }
    if t == "null" {
        return Value::Null;
    }
    if let Ok(i) = t.trim_end_matches(['l', 'L']).parse::<i64>() {
        return Value::Int(i);
    }
    match t.trim_end_matches(['d', 'D', 'f', 'F']).parse::<f64>() {
        Ok(f) => Value::Float(f),
        Err(_) => Value::Unknown,
    }
}

pub fn default_value_pub(f: &Node) -> Value {
    default_value(f)
}

fn default_value(f: &Node) -> Value {
    if let Some(l) = jx::get(f, "init_literal").filter(|l| !l.is_null()) {
        return lit_value(l);
    }
    match jx::str_(f, "type").unwrap_or("") {
        "int" | "long" | "short" | "byte" => Value::Int(0),
        "double" | "float" => Value::Float(0.0),
        "boolean" => Value::Bool(false),
        "char" => Value::str("\0"),
        _ => Value::Null,
    }
}

/// Сопоставление сегментов URL (с дырами `\0`) с шаблоном `@RequestMapping`.
pub fn match_template(segs: &[&str], tpl: &[String]) -> Option<IndexMap<String, Value>> {
    if segs.len() != tpl.len() && !(segs.last().is_some_and(|s| s.contains('\0')) && segs.len() < tpl.len()) {
        return None;
    }
    let mut b = IndexMap::new();
    for (i, t) in tpl.iter().enumerate() {
        let s = segs.get(i).copied().unwrap_or("\0");
        if t.starts_with('{') && t.ends_with('}') {
            b.insert(t[1..t.len() - 1].to_string(), if s.contains('\0') { Value::Unknown } else { Value::str(s) });
            continue;
        }
        if s.contains('\0') {
            let pat = format!("^{}$", s.split('\0').map(regex::escape).collect::<Vec<_>>().join(".*"));
            if !Regex::new(&pat).map(|re| re.is_match(t)).unwrap_or(false) {
                return None;
            }
            continue;
        }
        if s != t {
            return None;
        }
    }
    Some(b)
}

pub fn iter_items(v: &Value) -> (Vec<Value>, bool) {
    match v {
        Value::List(l) => {
            let l = l.borrow();
            (l.items.clone(), l.exact)
        }
        Value::Map(m) => {
            let m = m.borrow();
            (m.data.values().map(|(k, _)| k.clone()).collect(), m.exact)
        }
        _ => (Vec::new(), false),
    }
}

/// Выражение ответа — отказ: `new <обёртка>(<статус не успеха>, ...)` (в т.ч. внутри ok/status/body) или null.
fn is_failure_expr(e: &Json, env: Option<&Envelope>) -> bool {
    if !e.is_object() {
        return false;
    }
    if let (Some(new), Some(env)) = (jx::get(e, "new"), env) {
        if env.is_type(new.as_str()) {
            let args = list_of(e, "args");
            return match args.first() {
                Some(a) if a.is_object() && has(a, "lit") => env.lit_is_failure(&a["lit"]),
                _ => false,
            };
        }
    } else if has(e, "new") {
        return false;
    }
    if has(e, "call") && matches!(jx::str_(e, "callee"), Some("ok" | "status" | "body")) {
        if let Some(last) = list_of(e, "args").last() {
            return is_failure_expr(last, env);
        }
    }
    has(e, "lit") && jx::str_(e, "type") == Some("null")
}

/// Плечо кончается отказом на всех путях: `throw`, `return` обёртки со статусом не успеха или `null`.
pub fn arm_fails(stmts: &[Json], env: Option<&Envelope>) -> bool {
    let Some(last) = stmts.last() else { return false };
    match jx::str_(last, "op") {
        Some("throw") => true,
        Some("return") => {
            let e = jx::get(last, "expr");
            if let Some(e) = e.filter(|e| e.is_object() && has(e, "name") && !has(e, "call")) {
                let var = jx::str_(e, "name").unwrap_or("");
                return stmts[..stmts.len() - 1].iter().any(|x| sets_failure_status(x, var, env));
            }
            e.is_some_and(|e| is_failure_expr(e, env))
        }
        Some("if") => json_has_items(last, "else") && arm_fails(list_of(last, "then"), env) && arm_fails(list_of(last, "else"), env),
        Some("block" | "try") => arm_fails(list_of(last, "body"), env),
        _ => false,
    }
}

fn json_has_items(e: &Json, key: &str) -> bool {
    jx::get(e, key).is_some_and(json_truthy)
}

/// `var.set<Статус>(<не успех>)` на верхнем уровне плеча.
fn sets_failure_status(stmt: &Json, var: &str, env: Option<&Envelope>) -> bool {
    let e = if jx::str_(stmt, "op") == Some("expr") { jx::get(stmt, "expr") } else { None };
    let (Some(env), Some(e)) = (env, e) else { return false };
    if !e.is_object() || jx::str_(e, "callee") != Some(env.setter().as_str()) {
        return false;
    }
    let recv = jx::get(e, "recv");
    let args = list_of(e, "args");
    recv.is_some_and(|r| jx::str_(r, "name") == Some(var))
        && args.first().is_some_and(|a| a.is_object() && has(a, "lit") && env.lit_is_failure(&a["lit"]) && jx::str_(a, "type") == Some("int"))
}

/// Все `call_site` в операторах (для журнала отсева), в порядке обхода.
pub fn iter_calls<'a>(x: &'a Json, out: &mut Vec<&'a str>) {
    match x {
        Json::Object(o) => {
            if let Some(cs) = o.get("call").and_then(Json::as_str).filter(|c| c.starts_with("call:")) {
                out.push(cs);
            }
            for (k, v) in o {
                if k != "call" && (v.is_object() || v.is_array()) {
                    iter_calls(v, out);
                }
            }
        }
        Json::Array(a) => {
            for v in a {
                iter_calls(v, out);
            }
        }
        _ => {}
    }
}

/// `s.encode().decode("unicode_escape")`: разбор обратных косых черт, не-ASCII байты — как латиница-1.
pub fn unicode_escape(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = String::new();
    let mut i = 0;
    while i < b.len() {
        let c = b[i];
        if c != b'\\' {
            out.push(c as char);
            i += 1;
            continue;
        }
        i += 1;
        let Some(&e) = b.get(i) else {
            out.push('\\');
            break;
        };
        i += 1;
        match e {
            b'\n' => {}
            b'\\' => out.push('\\'),
            b'\'' => out.push('\''),
            b'"' => out.push('"'),
            b'a' => out.push('\x07'),
            b'b' => out.push('\x08'),
            b'f' => out.push('\x0c'),
            b'n' => out.push('\n'),
            b'r' => out.push('\r'),
            b't' => out.push('\t'),
            b'v' => out.push('\x0b'),
            b'0'..=b'7' => {
                let mut v = (e - b'0') as u32;
                let mut k = 0;
                while k < 2 && i < b.len() && (b'0'..=b'7').contains(&b[i]) {
                    v = v * 8 + (b[i] - b'0') as u32;
                    i += 1;
                    k += 1;
                }
                out.push(char::from_u32(v).unwrap_or('\u{fffd}'));
            }
            b'x' | b'u' | b'U' => {
                let n = match e {
                    b'x' => 2,
                    b'u' => 4,
                    _ => 8,
                };
                let hex = std::str::from_utf8(&b[i..(i + n).min(b.len())]).unwrap_or("");
                match u32::from_str_radix(hex, 16) {
                    Ok(v) if hex.len() == n => {
                        out.push(char::from_u32(v).unwrap_or('\u{fffd}'));
                        i += n;
                    }
                    _ => {
                        out.push('\\');
                        out.push(e as char);
                    }
                }
            }
            other => {
                out.push('\\');
                out.push(other as char);
            }
        }
    }
    out
}

/// Описание нужное `UnresolvedCalls` для library: режим `emit`.
pub fn unresolved_emit(flags: &RuleFlags) -> bool {
    flags.unresolved_receiver_calls == UnresolvedCalls::Emit
}

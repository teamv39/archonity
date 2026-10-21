//! Значения исполнителя M4 (`engine/executor/values.py`): конкретные, частично известные и UNKNOWN.
//!
//! В Python конкретные значения Java — `int`/`float`/`str`/`bool`/`None`, остальное — классы с `eq=False`: равенство
//! по ссылке, общая изменяемая ссылка. В Rust это `Rc<RefCell<…>>` ([`Shared`]); сравнение по ссылке — [`ident`].
//! Порядок вставки в словарях Python значим, поэтому везде `IndexMap`.
//!
//! Не держим `borrow()`/`borrow_mut()` через вызовы интерпретатора: клонируем нужное и отпускаем.

use std::cell::{Cell, RefCell};
use std::rc::Rc;

use chrono::NaiveDateTime;
use indexmap::IndexMap;

use crate::pyfmt::float_repr;

/// Общая изменяемая ссылка: объект в Python, на который указывают несколько имён.
pub type Shared<T> = Rc<RefCell<T>>;

pub fn shared<T>(v: T) -> Shared<T> {
    Rc::new(RefCell::new(v))
}

thread_local! {
    static UID: Cell<u64> = const { Cell::new(1) };
}

/// Следующий номер объекта: объекты с номером не меньше созданы позже этого момента.
pub fn next_uid() -> u64 {
    UID.with(|c| {
        let v = c.get();
        c.set(v + 1);
        v
    })
}

/// Значение Java в исполнителе. `Unknown` — одно на процесс; `Null` — `None`.
#[derive(Clone, Debug)]
pub enum Value {
    Unknown,
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(Rc<str>),
    Obj(Shared<Obj>),
    Enum(Shared<EnumV>),
    List(Shared<ListV>),
    Map(Shared<MapV>),
    Optional(Shared<OptionalV>),
    Wrapper(Shared<Wrapper>),
    Lambda(Shared<Lambda>),
    MethodRef(Shared<MethodRef>),
    Bean(Shared<Bean>),
    TypeRef(Shared<TypeRef>),
    Date(Shared<DateV>),
    Json(Shared<JsonV>),
    Concat(Shared<Concat>),
}

/// Ключ словаря `MapV`: в Python — любой хэшируемый объект. Равные по `==` числа и булевы — один ключ (`1 == 1.0 == True`).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum MapKey {
    Null,
    Int(i64),
    /// Биты `f64` (нецелое).
    Float(u64),
    Str(Rc<str>),
    /// Адрес общей ссылки (`id(x)`).
    Ref(usize),
}

/// Объект класса проекта или DTO. Поле `uid` — номер создания ([`next_uid`]).
#[derive(Debug)]
pub struct Obj {
    pub ty: Option<String>,
    pub fields: IndexMap<String, Value>,
    /// `true`: поля, которых нет в `fields`, неизвестны; `false` — отсутствующее поле равно null.
    pub open: bool,
    /// Результат неточного запроса к БД без Optional: есть ли строка, неизвестно.
    pub maybe_null: bool,
    pub uid: u64,
}

#[derive(Debug)]
pub struct EnumV {
    pub ty: String,
    pub constant: String,
    pub ordinal: Option<i64>,
    pub fields: IndexMap<String, Value>,
}

/// Список или множество. `exact == false` — элементы известны не все.
#[derive(Debug)]
pub struct ListV {
    pub items: Vec<Value>,
    pub exact: bool,
    pub elem_type: Option<String>,
    pub is_set: bool,
    pub uid: u64,
}

#[derive(Debug)]
pub struct MapV {
    /// Ключ нормализован ([`map_key`]); хранится исходный ключ и значение. Исходный ключ при перезаписи сохраняется.
    pub data: IndexMap<MapKey, (Value, Value)>,
    pub exact: bool,
}

/// `value`: `Null` — пусто, `Unknown` — неизвестно, есть ли значение. `maybe` — значение, если оно есть.
#[derive(Debug)]
pub struct OptionalV {
    pub value: Value,
    pub maybe: bool,
}

/// `HttpEntity` / `ResponseEntity`.
#[derive(Debug)]
pub struct Wrapper {
    pub body: Value,
    pub kind: String,
}

/// Отложенный блок (R16). Тело — узлы IR как есть (`serde_json::Value`, порядок ключей сохранён).
#[derive(Debug)]
pub struct Lambda {
    pub params: Vec<String>,
    pub body: Rc<Vec<serde_json::Value>>,
    pub env: IndexMap<String, Value>,
    pub this: Value,
    pub method: String,
    pub line: i64,
}

#[derive(Debug)]
pub struct MethodRef {
    pub target: Option<String>,
    pub call: Option<String>,
}

/// Поле-зависимость Spring (`@Autowired`).
#[derive(Debug)]
pub struct Bean {
    pub ty: Option<String>,
    pub name: String,
}

/// Имя класса в выражении (`StringUtils`, `OrderStatus`).
#[derive(Debug)]
pub struct TypeRef {
    pub fqn: String,
}

/// `java.util.Date` / `Calendar`: момент времени или неизвестно.
#[derive(Debug)]
pub struct DateV {
    pub value: Option<NaiveDateTime>,
    pub calendar: bool,
}

/// Строка JSON с известным исходным значением.
#[derive(Debug)]
pub struct JsonV {
    pub value: Value,
}

/// Строка из известных и неизвестных частей: части — `Value::Str` или `Value::Unknown`.
#[derive(Debug)]
pub struct Concat {
    pub parts: Vec<Value>,
}

/// Трёхзначная логика условий.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tri {
    True,
    False,
    Unknown,
}

impl Tri {
    pub fn value(self) -> Value {
        match self {
            Tri::True => Value::Bool(true),
            Tri::False => Value::Bool(false),
            Tri::Unknown => Value::Unknown,
        }
    }

    pub fn from_bool(b: bool) -> Tri {
        if b {
            Tri::True
        } else {
            Tri::False
        }
    }
}

// --- конструкторы и доступ ----------------------------------------------------------------------------------------

impl Value {
    pub fn str(s: &str) -> Value {
        Value::Str(Rc::from(s))
    }

    pub fn string(s: String) -> Value {
        Value::Str(Rc::from(s))
    }

    pub fn is_unknown(&self) -> bool {
        matches!(self, Value::Unknown)
    }

    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    /// `int`, но не `bool` (в Python `bool` — подкласс `int`; места, где он нужен, проверяют `Bool` отдельно).
    pub fn as_int(&self) -> Option<i64> {
        match self {
            Value::Int(i) => Some(*i),
            _ => None,
        }
    }

    /// Целое или булево как целое: `isinstance(v, int)` Python.
    pub fn as_int_or_bool(&self) -> Option<i64> {
        match self {
            Value::Int(i) => Some(*i),
            Value::Bool(b) => Some(*b as i64),
            _ => None,
        }
    }

    /// `int`/`float`, но не `bool`.
    pub fn as_num(&self) -> Option<Num> {
        match self {
            Value::Int(i) => Some(Num::Int(*i)),
            Value::Float(f) => Some(Num::Float(*f)),
            _ => None,
        }
    }

    pub fn obj(ty: Option<&str>, fields: IndexMap<String, Value>, open: bool) -> Value {
        Value::Obj(shared(Obj::new(ty.map(str::to_string), fields, open)))
    }

    pub fn list(items: Vec<Value>, exact: bool) -> Value {
        Value::List(shared(ListV::new(items, exact)))
    }

    pub fn optional(value: Value, maybe: bool) -> Value {
        Value::Optional(shared(OptionalV { value, maybe }))
    }

    pub fn wrapper(body: Value, kind: &str) -> Value {
        Value::Wrapper(shared(Wrapper { body, kind: kind.to_string() }))
    }

    /// Значение из JSON-литерала IR или ячейки БД; составные JSON — `Unknown`.
    pub fn from_json(j: &serde_json::Value) -> Value {
        use serde_json::Value as J;
        match j {
            J::Null => Value::Null,
            J::Bool(b) => Value::Bool(*b),
            J::Number(n) => match n.as_i64() {
                Some(i) => Value::Int(i),
                None => Value::Float(n.as_f64().unwrap_or(f64::NAN)),
            },
            J::String(s) => Value::str(s),
            _ => Value::Unknown,
        }
    }

    /// Значение в JSON (ячейка БД): только примитивы; остальное — `None`.
    pub fn to_json(&self) -> Option<serde_json::Value> {
        use serde_json::Value as J;
        Some(match self {
            Value::Null => J::Null,
            Value::Bool(b) => J::Bool(*b),
            Value::Int(i) => J::from(*i),
            Value::Float(f) => serde_json::Number::from_f64(*f).map(J::Number).unwrap_or(J::Null),
            Value::Str(s) => J::String(s.to_string()),
            _ => return None,
        })
    }

    /// Адрес общей ссылки или `None` для примитива (`id(x)`).
    pub fn addr(&self) -> Option<usize> {
        Some(match self {
            Value::Obj(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Enum(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::List(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Map(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Optional(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Wrapper(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Lambda(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::MethodRef(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Bean(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::TypeRef(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Date(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Json(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Concat(r) => Rc::as_ptr(r) as *const u8 as usize,
            Value::Str(s) => Rc::as_ptr(s) as *const u8 as usize,
            _ => return None,
        })
    }
}

/// Число Python: `int` или `float`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Num {
    Int(i64),
    Float(f64),
}

impl Num {
    pub fn f(self) -> f64 {
        match self {
            Num::Int(i) => i as f64,
            Num::Float(f) => f,
        }
    }

    pub fn value(self) -> Value {
        match self {
            Num::Int(i) => Value::Int(i),
            Num::Float(f) => Value::Float(f),
        }
    }

    pub fn eq(self, o: Num) -> bool {
        match (self, o) {
            (Num::Int(a), Num::Int(b)) => a == b,
            (a, b) => a.f() == b.f(),
        }
    }

    pub fn lt(self, o: Num) -> bool {
        match (self, o) {
            (Num::Int(a), Num::Int(b)) => a < b,
            (a, b) => a.f() < b.f(),
        }
    }

    pub fn le(self, o: Num) -> bool {
        match (self, o) {
            (Num::Int(a), Num::Int(b)) => a <= b,
            (a, b) => a.f() <= b.f(),
        }
    }
}

impl Obj {
    pub fn new(ty: Option<String>, fields: IndexMap<String, Value>, open: bool) -> Obj {
        Obj { ty, fields, open, maybe_null: false, uid: next_uid() }
    }

    /// Поле, иначе `Unknown` (объект открыт) или `Null`.
    pub fn get(&self, name: &str) -> Value {
        match self.fields.get(name) {
            Some(v) => v.clone(),
            None => {
                if self.open {
                    Value::Unknown
                } else {
                    Value::Null
                }
            }
        }
    }
}

impl EnumV {
    pub fn get(&self, name: &str) -> Value {
        self.fields.get(name).cloned().unwrap_or(Value::Unknown)
    }
}

impl ListV {
    pub fn new(items: Vec<Value>, exact: bool) -> ListV {
        ListV { items, exact, elem_type: None, is_set: false, uid: next_uid() }
    }
}

impl Concat {
    /// Склейка частей; неизвестные части заменены `hole`.
    pub fn render(&self, hole: &str) -> String {
        self.parts.iter().map(|p| p.as_str().unwrap_or(hole)).collect()
    }
}

/// Нормализованный ключ словаря (Python: `1 == 1.0 == True`). `None` — ключ не хэшируемый примитив.
pub fn map_key(v: &Value) -> Option<MapKey> {
    Some(match v {
        Value::Null => MapKey::Null,
        Value::Bool(b) => MapKey::Int(*b as i64),
        Value::Int(i) => MapKey::Int(*i),
        Value::Float(f) => {
            if f.is_finite() && f.fract() == 0.0 && f.abs() < 9.0e18 {
                MapKey::Int(*f as i64)
            } else {
                MapKey::Float(f.to_bits())
            }
        }
        Value::Str(s) => MapKey::Str(s.clone()),
        other => MapKey::Ref(other.addr()?),
    })
}

impl MapV {
    pub fn new(exact: bool) -> MapV {
        MapV { data: IndexMap::new(), exact }
    }

    pub fn put(&mut self, k: Value, v: Value) {
        if let Some(key) = map_key(&k) {
            match self.data.get_mut(&key) {
                Some(slot) => slot.1 = v,
                None => {
                    self.data.insert(key, (k, v));
                }
            }
        }
    }

    pub fn get(&self, k: &Value) -> Option<Value> {
        map_key(k).and_then(|key| self.data.get(&key)).map(|(_, v)| v.clone())
    }
}

/// `a is b`: тождество объектов. Для примитивов — равенство значения (приближение к кешу объектов CPython: числа
/// и короткие строки, которые Python отдаёт одним и тем же объектом, в обоих путях разбора ведут себя как один).
pub fn ident(a: &Value, b: &Value) -> bool {
    use Value::*;
    match (a, b) {
        (Unknown, Unknown) | (Null, Null) => true,
        (Bool(x), Bool(y)) => x == y,
        (Int(x), Int(y)) => x == y,
        (Float(x), Float(y)) => x == y || (x.is_nan() && y.is_nan()),
        (Str(x), Str(y)) => Rc::ptr_eq(x, y) || (x == y && x.chars().count() <= 1),
        _ => match (a.addr(), b.addr()) {
            (Some(x), Some(y)) => x == y && std::mem::discriminant(a) == std::mem::discriminant(b),
            _ => false,
        },
    }
}


// --- приведения как в Python ---------------------------------------------------------------------------------------

/// `str(v)` Python для значений, которые лежат в ячейках БД и условиях.
pub fn py_str(v: &Value) -> String {
    match v {
        Value::Null => "None".to_string(),
        Value::Bool(b) => if *b { "True" } else { "False" }.to_string(),
        Value::Int(i) => i.to_string(),
        Value::Float(f) => float_repr(*f),
        Value::Str(s) => s.to_string(),
        Value::Unknown => "UNKNOWN".to_string(),
        Value::Enum(e) => {
            let e = e.borrow();
            format!("{}.{}", e.ty.rsplit('.').next().unwrap_or(""), e.constant)
        }
        Value::Obj(o) => {
            let o = o.borrow();
            format!("Obj<{}#{}>", o.ty.as_deref().unwrap_or("?").rsplit('.').next().unwrap_or(""), o.uid)
        }
        other => format!("<{:#x}>", other.addr().unwrap_or(0)),
    }
}

/// `bool(v)` Python для примитивов; прочие объекты истинны.
pub fn py_truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Int(i) => *i != 0,
        Value::Float(f) => *f != 0.0,
        Value::Str(s) => !s.is_empty(),
        _ => true,
    }
}

/// `float(v)` Python: `None` вместо `ValueError`/`TypeError`.
pub fn py_float(v: &Value) -> Option<f64> {
    match v {
        Value::Bool(b) => Some(*b as i64 as f64),
        Value::Int(i) => Some(*i as f64),
        Value::Float(f) => Some(*f),
        Value::Str(s) => s.trim().parse::<f64>().ok(),
        _ => None,
    }
}

// --- строки и конкатенация -----------------------------------------------------------------------------------------

/// `String.valueOf`: строка или `Unknown`.
pub fn to_jstr(v: &Value) -> Value {
    match v {
        Value::Str(_) => v.clone(),
        Value::Null => Value::str("null"),
        Value::Bool(b) => Value::str(if *b { "true" } else { "false" }),
        Value::Int(i) => Value::string(i.to_string()),
        Value::Float(f) => {
            if *f != f.trunc() || f.abs() >= 1e7 {
                Value::string(float_repr(*f))
            } else {
                Value::string(format!("{f:.1}"))
            }
        }
        Value::Enum(e) => Value::str(&e.borrow().constant),
        _ => Value::Unknown,
    }
}

fn parts_of(v: &Value) -> Vec<Value> {
    match v {
        Value::Concat(c) => c.borrow().parts.clone(),
        other => vec![to_jstr(other)],
    }
}

/// Конкатенация строк Java: известные части склеиваются, неизвестные сохраняются как дыры.
pub fn concat(a: &Value, b: &Value) -> Value {
    let mut parts: Vec<Value> = Vec::new();
    for p in parts_of(a).into_iter().chain(parts_of(b)) {
        match (&p, parts.last_mut()) {
            (Value::Str(s), Some(Value::Str(prev))) => {
                let mut joined = String::with_capacity(prev.len() + s.len());
                joined.push_str(prev);
                joined.push_str(s);
                *prev = Rc::from(joined);
            }
            _ => parts.push(p),
        }
    }
    if parts.iter().all(|p| matches!(p, Value::Str(_))) {
        let s: String = parts.iter().map(|p| p.as_str().unwrap()).collect();
        Value::string(s)
    } else {
        Value::Concat(shared(Concat { parts }))
    }
}

// --- трёхзначная логика --------------------------------------------------------------------------------------------

/// Значение условия: `True`, `False` или `Unknown`.
pub fn tri(v: &Value) -> Tri {
    match v {
        Value::Bool(b) => Tri::from_bool(*b),
        _ => Tri::Unknown,
    }
}

pub fn t_not(a: Tri) -> Tri {
    match a {
        Tri::True => Tri::False,
        Tri::False => Tri::True,
        Tri::Unknown => Tri::Unknown,
    }
}

pub fn t_and(a: Tri, b: Tri) -> Tri {
    if a == Tri::False || b == Tri::False {
        Tri::False
    } else if a == Tri::True && b == Tri::True {
        Tri::True
    } else {
        Tri::Unknown
    }
}

pub fn t_or(a: Tri, b: Tri) -> Tri {
    if a == Tri::True || b == Tri::True {
        Tri::True
    } else if a == Tri::False && b == Tri::False {
        Tri::False
    } else {
        Tri::Unknown
    }
}

// --- слияние и сравнение -------------------------------------------------------------------------------------------

/// Слияние значений двух путей: совпадает — значение, иначе `Unknown` (объекты одного типа — по полям).
pub fn join(a: &Value, b: &Value) -> Value {
    use Value::*;
    match (a, b) {
        (Unknown, _) | (_, Unknown) => return Unknown,
        _ => {}
    }
    if let (Some(x), Some(y)) = (a.addr(), b.addr()) {
        if x == y && std::mem::discriminant(a) == std::mem::discriminant(b) && !matches!(a, Str(_)) {
            return a.clone();
        }
    }
    match (a, b) {
        (Null, Null) => Null,
        (Bool(x), Bool(y)) if x == y => a.clone(),
        (Int(x), Int(y)) if x == y => a.clone(),
        (Float(x), Float(y)) if x == y => a.clone(),
        (Str(x), Str(y)) if x == y => a.clone(),
        (Enum(x), Enum(y)) => {
            let (x, y) = (x.borrow(), y.borrow());
            if x.ty == y.ty && x.constant == y.constant {
                a.clone()
            } else {
                Unknown
            }
        }
        (Obj(x), Obj(y)) => {
            let (x, y) = (x.borrow(), y.borrow());
            if x.ty != y.ty {
                return Unknown;
            }
            let mut keys: Vec<&String> = x.fields.keys().collect();
            for k in y.fields.keys() {
                if !x.fields.contains_key(k) {
                    keys.push(k);
                }
            }
            let fields: IndexMap<String, Value> = keys.into_iter().map(|k| (k.clone(), join(&x.get(k), &y.get(k)))).collect();
            Value::Obj(shared(self::Obj::new(x.ty.clone(), fields, x.open || y.open)))
        }
        (Wrapper(x), Wrapper(y)) => {
            let (x, y) = (x.borrow(), y.borrow());
            Value::wrapper(join(&x.body, &y.body), &x.kind)
        }
        (Optional(x), Optional(y)) => {
            let (xb, yb) = (x.borrow(), y.borrow());
            if xb.value.is_null() && yb.value.is_null() {
                return a.clone();
            }
            if xb.value.is_null() || yb.value.is_null() {
                return Value::optional(Unknown, false);
            }
            Value::optional(join(&xb.value, &yb.value), false)
        }
        (List(x), List(y)) => {
            let (x, y) = (x.borrow(), y.borrow());
            if x.exact && y.exact && x.items.len() == y.items.len() && x.items.iter().zip(&y.items).all(|(p, q)| ident(p, q)) {
                return a.clone();
            }
            let mut items = x.items.clone();
            for q in &y.items {
                if !x.items.iter().any(|p| ident(p, q)) {
                    items.push(q.clone());
                }
            }
            let mut l = ListV::new(items, false);
            l.elem_type = x.elem_type.clone().or_else(|| y.elem_type.clone());
            Value::List(shared(l))
        }
        _ => Unknown,
    }
}

fn is_prim(v: &Value) -> bool {
    matches!(v, Value::Int(_) | Value::Float(_) | Value::Str(_) | Value::Bool(_))
}

/// Сравнение `==`: для объектов — тождество, для строк и чисел — значение; результат — трёхзначный.
pub fn same_value(a: &Value, b: &Value) -> Tri {
    use Value::*;
    if a.is_unknown() || b.is_unknown() || matches!(a, Concat(_)) || matches!(b, Concat(_)) {
        return Tri::Unknown;
    }
    if a.is_null() || b.is_null() {
        if matches!(a, Optional(_)) || matches!(b, Optional(_)) {
            return Tri::False;
        }
        let maybe = |v: &Value| matches!(v, Obj(o) if o.borrow().maybe_null);
        if maybe(a) || maybe(b) {
            return Tri::Unknown;
        }
        return Tri::from_bool(a.is_null() && b.is_null());
    }
    if let (Enum(x), Enum(y)) = (a, b) {
        let (x, y) = (x.borrow(), y.borrow());
        return Tri::from_bool(x.ty == y.ty && x.constant == y.constant);
    }
    if let (Some(x), Some(y)) = (a.as_num(), b.as_num()) {
        return Tri::from_bool(x.eq(y));
    }
    let str_or_bool = |v: &Value| matches!(v, Str(_) | Bool(_));
    if str_or_bool(a) && str_or_bool(b) {
        return Tri::from_bool(match (a, b) {
            (Str(x), Str(y)) => x == y,
            (Bool(x), Bool(y)) => x == y,
            _ => false,
        });
    }
    if is_prim(a) || is_prim(b) {
        if matches!(a, Enum(_)) || matches!(b, Enum(_)) {
            return Tri::Unknown;
        }
        // int/float/bool между собой сравниваются по значению; иначе типы разные — неизвестно
        let numlike = |v: &Value| v.as_int_or_bool().map(|i| Num::Int(i)).or_else(|| v.as_num());
        if let (Some(x), Some(y)) = (numlike(a), numlike(b)) {
            return Tri::from_bool(x.eq(y));
        }
        return Tri::Unknown;
    }
    Tri::from_bool(ident(a, b))
}

/// `Object.equals` для значений без проектного `equals`.
pub fn equals_value(a: &Value, b: &Value) -> Tri {
    let r = same_value(a, b);
    if r != Tri::False {
        return r;
    }
    if matches!((a, b), (Value::Obj(_), Value::Obj(_))) {
        return Tri::Unknown;
    }
    r
}

/// Число из значения (BigDecimal, `Double.parseDouble`, строки с ценой).
pub fn num(v: &Value) -> Value {
    match v {
        Value::Bool(_) => Value::Unknown,
        Value::Int(_) | Value::Float(_) => v.clone(),
        Value::Str(s) => {
            let t = s.trim();
            if t.trim_start_matches('-').chars().all(|c| c.is_ascii_digit()) && !t.trim_start_matches('-').is_empty() {
                match s.trim().parse::<i64>() {
                    Ok(i) => Value::Int(i),
                    Err(_) => Value::Unknown,
                }
            } else {
                match t.parse::<f64>() {
                    Ok(f) => Value::Float(f),
                    Err(_) => Value::Unknown,
                }
            }
        }
        _ => Value::Unknown,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(x: &str) -> Value {
        Value::str(x)
    }

    #[test]
    fn concat_merges_known_parts() {
        let v = concat(&s("a"), &Value::Int(1));
        assert_eq!(v.as_str(), Some("a1"));
        let c = concat(&s("a"), &Value::Unknown);
        assert!(matches!(c, Value::Concat(_)));
        let d = concat(&c, &s("b"));
        match &d {
            Value::Concat(c) => assert_eq!(c.borrow().render("\0"), "a\0b"),
            _ => panic!(),
        }
    }

    #[test]
    fn to_jstr_floats() {
        assert_eq!(to_jstr(&Value::Float(5.0)).as_str(), Some("5.0"));
        assert_eq!(to_jstr(&Value::Float(0.1)).as_str(), Some("0.1"));
        assert_eq!(to_jstr(&Value::Float(1e7)).as_str(), Some("10000000.0"));
        assert_eq!(to_jstr(&Value::Null).as_str(), Some("null"));
    }

    #[test]
    fn three_valued() {
        assert_eq!(same_value(&Value::Int(1), &Value::Float(1.0)), Tri::True);
        assert_eq!(same_value(&Value::Null, &Value::Unknown), Tri::Unknown);
        assert_eq!(same_value(&s("a"), &Value::Int(1)), Tri::Unknown);
        assert_eq!(same_value(&Value::Null, &s("a")), Tri::False);
        assert_eq!(t_and(Tri::Unknown, Tri::False), Tri::False);
        assert_eq!(t_or(Tri::Unknown, Tri::True), Tri::True);
    }

    #[test]
    fn num_parsing() {
        assert!(matches!(num(&s(" 12 ")), Value::Int(12)));
        assert!(matches!(num(&s("1.5")), Value::Float(f) if f == 1.5));
        assert!(num(&s("abc")).is_unknown());
        assert!(num(&Value::Bool(true)).is_unknown());
        assert!(num(&s("--5")).is_unknown());
    }

    #[test]
    fn join_objects_by_fields() {
        let a = Value::obj(Some("T"), [("x".to_string(), Value::Int(1))].into_iter().collect(), false);
        let b = Value::obj(Some("T"), [("x".to_string(), Value::Int(2))].into_iter().collect(), false);
        match join(&a, &b) {
            Value::Obj(o) => assert!(o.borrow().fields["x"].is_unknown()),
            _ => panic!(),
        }
        assert!(matches!(join(&Value::Int(1), &Value::Int(1)), Value::Int(1)));
        assert!(join(&Value::Int(1), &Value::Int(2)).is_unknown());
    }

    #[test]
    fn map_keys_follow_python_equality() {
        let mut m = MapV::new(true);
        m.put(Value::Bool(true), Value::Int(1));
        m.put(Value::Int(1), Value::Int(2));
        m.put(Value::Float(1.0), Value::Int(3));
        assert_eq!(m.data.len(), 1);
        assert!(matches!(m.get(&Value::Int(1)), Some(Value::Int(3))));
    }
}

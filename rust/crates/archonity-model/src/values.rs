//! Значения исполнителя M4 (`engine/executor/values.py`): конкретные, частично известные и UNKNOWN.
//!
//! В Python конкретные значения Java — `int`/`float`/`str`/`bool`/`None`, остальное — классы с `eq=False`: равенство
//! по ссылке, общая изменяемая ссылка. В Rust это `Rc<RefCell<…>>` ([`Shared`]); сравнение по ссылке — [`ptr_eq`].
//! Порядок вставки в словарях Python значим, поэтому везде `IndexMap`.

use std::cell::RefCell;
use std::rc::Rc;

use chrono::NaiveDateTime;
use indexmap::IndexMap;

/// Общая изменяемая ссылка: объект в Python, на который указывают несколько имён.
pub type Shared<T> = Rc<RefCell<T>>;

pub fn shared<T>(v: T) -> Shared<T> {
    Rc::new(RefCell::new(v))
}

/// Тождество объектов (`a is b` в Python).
pub fn ptr_eq<T>(a: &Shared<T>, b: &Shared<T>) -> bool {
    Rc::ptr_eq(a, b)
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

/// Ключ словаря `MapV`: в Python — любой хэшируемый объект. Объекты без значения равенства — по адресу.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum MapKey {
    Null,
    Bool(bool),
    Int(i64),
    /// Биты `f64`.
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

/// Следующий номер объекта: объекты с номером не меньше созданы позже этого момента.
pub fn next_uid() -> u64 {
    todo!("этап 1: счётчик в thread_local")
}

pub fn is_unknown(v: &Value) -> bool {
    matches!(v, Value::Unknown)
}

impl Obj {
    pub fn new(ty: Option<String>, fields: IndexMap<String, Value>, open: bool) -> Obj {
        Obj { ty, fields, open, maybe_null: false, uid: next_uid() }
    }

    /// Поле или `Unknown` (объект открыт) / `Null`.
    pub fn get(&self, _name: &str) -> Value {
        todo!("этап 1")
    }
}

impl Concat {
    /// Склейка частей; дыра вместо неизвестной части.
    pub fn render(&self, _hole: &str) -> String {
        todo!("этап 1")
    }
}

/// Конкатенация строк Java: известные части склеиваются, неизвестные сохраняются как дыры.
pub fn concat(_a: &Value, _b: &Value) -> Value {
    todo!("этап 1")
}

/// `String.valueOf`: строка или `Unknown`.
pub fn to_jstr(_v: &Value) -> Value {
    todo!("этап 1: repr(float) как в Python")
}

/// Значение условия из значения.
pub fn tri(_v: &Value) -> Tri {
    todo!("этап 1")
}

pub fn t_not(_a: Tri) -> Tri {
    todo!("этап 1")
}

pub fn t_and(_a: Tri, _b: Tri) -> Tri {
    todo!("этап 1")
}

pub fn t_or(_a: Tri, _b: Tri) -> Tri {
    todo!("этап 1")
}

/// Слияние значений двух путей: совпадает — значение, иначе `Unknown` (объекты одного типа — по полям).
pub fn join(_a: &Value, _b: &Value) -> Value {
    todo!("этап 1")
}

/// Сравнение `==`: для объектов — тождество, для строк и чисел — значение; результат — трёхзначный.
pub fn same_value(_a: &Value, _b: &Value) -> Tri {
    todo!("этап 1")
}

/// `Object.equals` для значений без проектного `equals`.
pub fn equals_value(_a: &Value, _b: &Value) -> Tri {
    todo!("этап 1")
}

/// Число из значения (BigDecimal, `Double.parseDouble`, строки с ценой).
pub fn num(_v: &Value) -> Value {
    todo!("этап 1")
}

//! Флаги правил (`engine/rules.py`, `RuntimeRules`). Имена и значения те же, что у `run_eval.py`.

use anyhow::{bail, Result};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Constructors {
    CallerOnly,
    All,
    Off,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CollectionTables {
    Loaded,
    All,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnboundHandlers {
    Rebind,
    Keep,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnresolvedCalls {
    Emit,
    Mute,
}

/// Режимы правил M4 и M5. Умолчания — рекорд.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuleFlags {
    pub constructors: Constructors,
    pub collection_tables_on_read: CollectionTables,
    pub element_callbacks: bool,
    pub rabbitmq_delivery: bool,
    pub jackson_ctor: bool,
    pub lombok_tostring: bool,
    pub unbound_handlers: UnboundHandlers,
    pub unresolved_receiver_calls: UnresolvedCalls,
    pub m4_success_retry: bool,
    pub ref_explicit_id: bool,
    pub ref_idless_result: bool,
    pub consign_absent_group: bool,
}

impl Default for RuleFlags {
    fn default() -> Self {
        RuleFlags {
            constructors: Constructors::CallerOnly,
            collection_tables_on_read: CollectionTables::Loaded,
            element_callbacks: true,
            rabbitmq_delivery: true,
            jackson_ctor: true,
            lombok_tostring: true,
            unbound_handlers: UnboundHandlers::Rebind,
            unresolved_receiver_calls: UnresolvedCalls::Emit,
            m4_success_retry: true,
            ref_explicit_id: true,
            ref_idless_result: true,
            consign_absent_group: true,
        }
    }
}

impl RuleFlags {
    /// Задаёт флаг по имени `RuntimeRules` и тексту значения (`"on"`, `"caller_only"`, …).
    pub fn set(&mut self, name: &str, value: &str) -> Result<()> {
        let on_off = |v: &str| -> Result<bool> {
            match v {
                "on" => Ok(true),
                "off" => Ok(false),
                _ => bail!("{name}: {v:?}, ожидается on или off"),
            }
        };
        match (name, value) {
            ("constructors", "caller_only") => self.constructors = Constructors::CallerOnly,
            ("constructors", "all") => self.constructors = Constructors::All,
            ("constructors", "off") => self.constructors = Constructors::Off,
            ("collection_tables_on_read", "loaded") => self.collection_tables_on_read = CollectionTables::Loaded,
            ("collection_tables_on_read", "all") => self.collection_tables_on_read = CollectionTables::All,
            ("element_callbacks", v) => self.element_callbacks = on_off(v)?,
            ("rabbitmq_delivery", v) => self.rabbitmq_delivery = on_off(v)?,
            ("jackson_ctor", v) => self.jackson_ctor = on_off(v)?,
            ("lombok_tostring", v) => self.lombok_tostring = on_off(v)?,
            ("unbound_handlers", "rebind") => self.unbound_handlers = UnboundHandlers::Rebind,
            ("unbound_handlers", "keep") => self.unbound_handlers = UnboundHandlers::Keep,
            ("unresolved_receiver_calls", "emit") => self.unresolved_receiver_calls = UnresolvedCalls::Emit,
            ("unresolved_receiver_calls", "mute") => self.unresolved_receiver_calls = UnresolvedCalls::Mute,
            ("m4_success_retry", v) => self.m4_success_retry = on_off(v)?,
            ("ref_explicit_id", v) => self.ref_explicit_id = on_off(v)?,
            ("ref_idless_result", v) => self.ref_idless_result = on_off(v)?,
            ("consign_absent_group", v) => self.consign_absent_group = on_off(v)?,
            _ => bail!("неизвестный флаг или значение: {name}={value}"),
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_are_the_record() {
        let f = RuleFlags::default();
        assert_eq!(f.constructors, Constructors::CallerOnly);
        assert!(f.m4_success_retry && f.jackson_ctor && f.ref_explicit_id && f.ref_idless_result
            && f.consign_absent_group);
    }

    #[test]
    fn set_rejects_unknown() {
        let mut f = RuleFlags::default();
        assert!(f.set("constructors", "maybe").is_err());
        f.set("constructors", "off").unwrap();
        assert_eq!(f.constructors, Constructors::Off);
    }
}

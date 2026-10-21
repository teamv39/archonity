//! Правило Spring Security при входе (`engine/spring_security.py::apply_spring_security`).
//!
//! Вход — исполненный метод с вызовом `AuthenticationManager.authenticate`. Его исполняет DaoAuthenticationProvider:
//! `loadUserByUsername` реализации `UserDetailsService` того же модуля (SQL — к таблицам `data_access` этого метода,
//! ленивые коллекции по R10 не загружены), затем методы `UserDetails`. Фильтры — `doFilterInternal` подклассов
//! `OncePerRequestFilter`. Имён проекта правило не знает: только типы и методы контракта.

use std::collections::BTreeSet;

use anyhow::Result;
use archonity_io::{jx, DecisionLedger, SkeletonIndex};

const AUTH_MANAGER: &str = "org.springframework.security.authentication.AuthenticationManager";
/// Методы `UserDetails`, которые провайдер вызывает в `authenticate`. `getUsername` не вызывает.
const PROVIDER_USER_METHODS: [&str; 6] =
    ["isAccountNonLocked", "isEnabled", "isAccountNonExpired", "getPassword", "isCredentialsNonExpired", "getAuthorities"];
const RULE: &str = "spring_security";

pub fn apply_spring_security(
    index: &SkeletonIndex,
    methods: &mut BTreeSet<String>,
    calls: &mut BTreeSet<(String, String)>,
    data: &mut BTreeSet<(String, String)>,
    ledger: &mut DecisionLedger,
) -> Result<()> {
    let entries: Vec<String> = methods
        .iter()
        .filter(|m| {
            index
                .cs_nodes_by_method
                .get(*m)
                .is_some_and(|cs| cs.iter().any(|c| jx::str_(c, "callee") == Some("authenticate") && jx::str_(c, "receiver_type") == Some(AUTH_MANAGER)))
        })
        .cloned()
        .collect();
    let execute = |methods: &mut BTreeSet<String>, ledger: &mut DecisionLedger, m: &str| -> Result<()> {
        if !methods.contains(m) {
            ledger.execute(m, "FRAMEWORK_RULE", RULE, Default::default())?;
        }
        methods.insert(m.to_string());
        Ok(())
    };
    for entry in entries {
        let module = index.n.get(&entry).and_then(|n| jx::str_(n, "module"));
        // UserDetailsService: загрузка пользователя
        for ud in methods_of(index, &types_with_super(index, module, "UserDetailsService", "implements_raw"), &["loadUserByUsername"]) {
            execute(methods, ledger, &ud)?;
            let tables: Vec<String> = index.wiring.get("data_access").and_then(|w| w.get(&ud)).map(|s| s.iter().cloned().collect()).unwrap_or_default();
            for t in tables {
                let dec = index.entities.collection_table_loaded(&ud, &t);
                if dec.as_ref().map_or(true, |d| d.0) {
                    data.insert((ud.clone(), t.clone()));
                    ledger.include("data", &ud, &t, "FRAMEWORK_RULE", RULE, Default::default())?;
                }
            }
        }
        // Фильтр запросов
        for f in methods_of(index, &types_with_super(index, None, "OncePerRequestFilter", "extends_raw"), &["doFilterInternal"]) {
            execute(methods, ledger, &f)?;
        }
        // UserDetails: методы, которые вызывает провайдер
        let called_here: BTreeSet<&str> = index.cs_nodes_by_method.get(&entry).map(|cs| cs.iter().filter_map(|c| jx::str_(c, "callee")).collect()).unwrap_or_default();
        for um in methods_of(index, &types_with_super(index, module, "UserDetails", "implements_raw"), &PROVIDER_USER_METHODS) {
            execute(methods, ledger, &um)?;
            let name = index.n.get(&um).and_then(|n| jx::str_(n, "name")).unwrap_or("");
            if called_here.contains(name) {
                calls.insert((entry.clone(), um.clone()));
                ledger.include("calls", &entry, &um, "FRAMEWORK_RULE", &format!("{RULE}:R6"), Default::default())?;
            }
        }
    }
    Ok(())
}

/// Типы модуля (или всего проекта при `module = None`), у которых в `extends`/`implements` есть `simple`.
fn types_with_super(index: &SkeletonIndex, module: Option<&str>, simple: &str, attr: &str) -> BTreeSet<String> {
    index
        .type_nodes
        .iter()
        .filter(|(_, n)| (module.is_none() || jx::str_(n, "module") == module) && jx::strs(n, attr).contains(&simple))
        .map(|(id, _)| id.clone())
        .collect()
}

/// Методы типов `owners` с именами из `names`, по ID.
fn methods_of(index: &SkeletonIndex, owners: &BTreeSet<String>, names: &[&str]) -> Vec<String> {
    let mut out: Vec<String> = owners
        .iter()
        .flat_map(|o| index.methods_by_owner.get(o).into_iter().flatten())
        .filter(|(_, n)| jx::str_(n, "name").is_some_and(|x| names.contains(&x)))
        .map(|(id, _)| id.clone())
        .collect();
    out.sort();
    out
}

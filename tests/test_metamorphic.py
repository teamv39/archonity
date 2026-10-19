"""Метаморфные тесты конвейера Archonity (Metamorphic Testing Suite).

Проверяют инварианты поведения без необходимости ручной разметки эталонов:
- MR-1: Абляция изолированных шагов (вычитание подграфа без побочных эффектов).
- MR-2: Идемпотентность повторного вызова read-only шагов.
- MR-3: Устойчивость поиска точки входа (BM25 retrieval) к парафразам и синонимам.
- MR-4: Структурные инварианты графа (Rule R19, легитимность вершин, 100% Evidence coverage).
- MR-5: Детерминизм исполнения.

Методология и теоретическое обоснование: docs/researches/metamorphic_testing.md
Правила тестирующей системы: docs/testing_system.md
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from engine.adapters.skeleton import load_json
from engine.pipeline import ArchonityPipeline
from engine.state import ScenarioState
from engine.rules import ScenarioProfile

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "hackaton" / "tt-challenge" / "skeleton" / "trainticket.json.gz"
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"
RULES_PATH = ROOT / "data" / "runtime_and_topology_rules.json"
IR_PATH = ROOT / "data" / "pool_ir.json"


@pytest.fixture(scope="module")
def ir_pipeline() -> ArchonityPipeline:
    """Инициализация эталонного конвейера (M1 Grounder + M4 IR Executor)."""
    return ArchonityPipeline(
        skeleton_path=SKELETON_PATH,
        targets_root=TARGETS_ROOT,
        rules_path=RULES_PATH,
        ir_path=IR_PATH,
        grounder="m1",
        executor="ir",
        unresolved_receiver_calls="emit",
        constructors="caller_only",
        jackson_ctor="on",
        lombok_tostring="on",
        unbound_handlers="rebind",
        spring_security="semantic",
        m4_m3_refs="off",
        module_roles="skeleton",
    )


class TestMetamorphicRelations:
    """Набор метаморфных тестов для конвейера статического анализа."""

    # ------------------------------------------------------------------
    # MR-1: Абляция терминальных/изолированных шагов
    # ------------------------------------------------------------------

    def test_mr1_terminal_step_ablation_s1_step14(self, ir_pipeline: ArchonityPipeline) -> None:
        r"""MR-1.1: Удаление шага 14 в S1 (просмотр страховки) удаляет ровно подграф страховки.
        
        Ожидаемое отношение:
            E(S1 \ {14}) == E(S1) \ E_exclusive(14)
            E(S1 \ {14}) \ E(S1) == ∅ (никаких ложных/случайных ребер не появляется).
        """
        s1_path = ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S1.json"
        s1_full = load_json(s1_path)

        m_full, c_full, r_full, d_full = ir_pipeline.run_scenario(s1_full)

        # Мутированный сценарий без шага 14
        s1_mut = dict(s1_full)
        s1_mut["steps"] = [st for st in s1_full["steps"] if st["n"] != 14]
        m_mut, c_mut, r_mut, d_mut = ir_pipeline.run_scenario(s1_mut)

        delta_m = m_full - m_mut
        delta_c = c_full - c_mut
        delta_r = r_full - r_mut
        delta_d = d_full - d_mut

        # Инвариант: новое ничего не появилось
        assert m_mut - m_full == set(), "В мутированном графе появились лишние методы"
        assert c_mut - c_full == set(), "В мутированном графе появились лишние calls"
        assert r_mut - r_full == set(), "В мутированном графе появились лишние remote"
        assert d_mut - d_full == set(), "В мутированном графе появились лишние data"

        # Инвариант дельты: пропали ровно 2 метода, 1 вызов, 1 обращение к БД страховки
        assert len(delta_m) == 2
        assert len(delta_c) == 1
        assert len(delta_r) == 0
        assert len(delta_d) == 1

        # Проверка конкретных сущностей подграфа ts-assurance-service
        for m in delta_m:
            assert "ts-assurance-service" in m
        for s, t in delta_c:
            assert "ts-assurance-service" in s and "ts-assurance-service" in t
        for src, tbl in delta_d:
            assert "ts-assurance-service" in src
            assert tbl == "res:table:ts-assurance-service.assurance"

    def test_mr1_terminal_step_ablation_s1_steps13_and_14(self, ir_pipeline: ArchonityPipeline) -> None:
        """MR-1.2: Удаление шагов 13 (багаж) и 14 (страховка) удаляет оба независимых подграфа."""
        s1_path = ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S1.json"
        s1_full = load_json(s1_path)

        m_full, c_full, r_full, d_full = ir_pipeline.run_scenario(s1_full)

        s1_mut = dict(s1_full)
        s1_mut["steps"] = [st for st in s1_full["steps"] if st["n"] not in (13, 14)]
        m_mut, c_mut, r_mut, d_mut = ir_pipeline.run_scenario(s1_mut)

        delta_m = m_full - m_mut
        delta_c = c_full - c_mut
        delta_d = d_full - d_mut

        assert m_mut - m_full == set()
        assert c_mut - c_full == set()
        assert d_mut - d_full == set()

        # Ровно 4 метода (2 consign + 2 assurance), 2 calls, 2 data
        assert len(delta_m) == 4
        assert len(delta_c) == 2
        assert len(delta_d) == 2

    # ------------------------------------------------------------------
    # MR-2: Идемпотентность read-only шагов
    # ------------------------------------------------------------------

    def test_mr2_readonly_step_idempotence(self, ir_pipeline: ArchonityPipeline) -> None:
        """MR-2: Повторный запуск того же read-only шага дает тождественный подграф."""
        s1_path = ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S1.json"
        s1_dict = load_json(s1_path)

        # Выполняем шаг запроса меню (шаг 4) через сессию M1 и исполнитель M4
        session = ir_pipeline.m1.begin(s1_dict)
        step_reqs = [session.ground(st) for st in s1_dict["steps"][:4]]
        step_menu = step_reqs[3]  # шаг 4: View the food menu

        profile = ScenarioProfile.from_scenario(s1_dict)
        state1 = ScenarioState.create_initial(scenario_profile=profile)
        for r in step_reqs[:3]:
            state1.apply_step(r, scenario_dict=s1_dict)

        ir_pipeline.m4.begin_scenario("S1_IDEMP")
        m1, c1, r1, d1 = ir_pipeline.m4.run_step(step_menu, state1, scenario=s1_dict)

        # Повторное выполнение того же шага из того же состояния
        ir_pipeline.m4.begin_scenario("S1_IDEMP")
        m2, c2, r2, d2 = ir_pipeline.m4.run_step(step_menu, state1, scenario=s1_dict)

        assert m1 == m2
        assert c1 == c2
        assert r1 == r2
        assert d1 == d2

    # ------------------------------------------------------------------
    # MR-3: Устойчивость поиска точки входа (BM25 Retrieval)
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("query", "expected_substring", "max_rank"),
        [
            ("Look up the assurance (insurance) record of the order", "AssuranceController#findAssuranceByOrderId", 1),
            ("Query the assurance insurance policy for this order", "AssuranceController#findAssuranceByOrderId", 4),
            ("Find insurance details by order id", "AssuranceController#findAssuranceByOrderId", 4),
            ("Get assurance of order", "AssuranceController#findAssuranceByOrderId", 2),
            ("Log in with username and password", "UserController#getToken", 1),
            ("Sign in user with login credentials", "UserController#getToken", 3),
            ("User authentication and login with password", "UserController#getToken", 3),
            ("Look up the luggage consignment record of the order", "ConsignController#findByOrderId", 1),
            ("Search luggage consign history by order identifier", "ConsignController#findByOrderId", 3),
        ],
    )
    def test_mr3_retrieval_robustness_synonyms(
        self,
        ir_pipeline: ArchonityPipeline,
        query: str,
        expected_substring: str,
        max_rank: int,
    ) -> None:
        """MR-3: Парафразы и синонимы удерживают целевой обработчик в Top-K кандидатов BM25."""
        ranked = ir_pipeline.m1.retriever.rank_bm25(query)
        matching = [i + 1 for i, h in enumerate(ranked) if expected_substring in h]
        assert matching, f"Обработчик {expected_substring} не найден в ранжировании для запроса '{query}'"
        best_rank = matching[0]
        assert best_rank <= max_rank, (
            f"Ранг {best_rank} для запроса '{query}' превысил порог {max_rank} (цель: {expected_substring})"
        )

    # ------------------------------------------------------------------
    # MR-4: Структурные инварианты графа и 100% Evidence Coverage
    # ------------------------------------------------------------------

    def test_mr4_structural_invariants(self, ir_pipeline: ArchonityPipeline) -> None:
        """MR-4: Все вершины принадлежат скелету, выполняется правило R19, 100% рёбер покрыты Evidence."""
        s0_path = ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json"
        s0_dict = load_json(s0_path)

        methods, calls, remote, data = ir_pipeline.run_scenario(s0_dict)

        # 1. Легитимность методов в index.N
        for m in methods:
            assert m in ir_pipeline.index.N, f"Метод {m} отсутствует в скелете проекта"
            kind = ir_pipeline.index.N[m].get("kind")
            assert kind in ("method", "constructor"), f"Узел {m} имеет неверный kind: {kind}"

        # 2. Легитимность таблиц
        for _, tbl in data:
            assert tbl in ir_pipeline.index.N or tbl.startswith("res:table:"), (
                f"Таблица {tbl} отсутствует в скелете проекта"
            )

        # 3. Гарантия правила R19
        for src, tgt in calls:
            assert src in methods, f"Источник call {src} не входит в executes"
            assert tgt in methods, f"Цель call {tgt} не входит в executes"
        for src, tgt in remote:
            assert src in methods, f"Источник remote {src} не входит в executes"
            assert tgt in methods, f"Цель remote {tgt} не входит в executes"
        for src, _ in data:
            assert src in methods, f"Источник data {src} не входит в executes"

        # 4. 100% покрытие Decision Ledger (evidence v2)
        decisions = ir_pipeline.ledger.to_dict()["scenarios"]["S0"]
        for m in methods:
            key = f"executes|scenario:S0|{m}"
            assert key in decisions, f"Ребро {key} отсутствует в Decision Ledger"
            assert decisions[key]["rule"], f"У ребра {key} не указано правило"
        for s, t in calls:
            key = f"calls|{s}|{t}"
            assert key in decisions, f"Ребро {key} отсутствует в Decision Ledger"
            assert decisions[key]["rule"], f"У ребра {key} не указано правило"
        for s, t in data:
            key = f"data|{s}|{t}"
            assert key in decisions, f"Ребро {key} отсутствует в Decision Ledger"
            assert decisions[key]["rule"], f"У ребра {key} не указано правило"

    # ------------------------------------------------------------------
    # MR-5: Детерминизм и калибровка
    # ------------------------------------------------------------------

    def test_mr5_execution_determinism(self, ir_pipeline: ArchonityPipeline) -> None:
        """MR-5: Два последовательных прогона сценария дают идентичные множества рёбер."""
        s0_path = ROOT / "hackaton" / "tt-challenge" / "scenarios" / "S0.json"
        s0_dict = load_json(s0_path)

        m1, c1, r1, d1 = ir_pipeline.run_scenario(s0_dict)
        m2, c2, r2, d2 = ir_pipeline.run_scenario(s0_dict)

        assert m1 == m2
        assert c1 == c2
        assert r1 == r2
        assert d1 == d2

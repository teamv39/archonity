"""Модуль интеграции AST IR тел методов (archparse / pool_ir.json) с движком Archonity.

Реализует спецификацию ADR-005 (M2: IR тел методов -> M4: Исполнение графа):
1. Индексация тел ключевых методов по (method_id, file, line, col).
2. Активация Enum-вызовов (правило R7: OrderStatus.*.getCode(), SeatClass.*.getCode()).
3. Разрешение предикатов активации вызовов (Call Guard Resolution) на основе
   семантики профиля сценария (ScenarioProfile) и состояния БД (ScenarioState).
4. Автоматическая сборка и валидация через gradle при наличии JDK.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.branch_rules import BranchRulesRegistry
from engine.rules import ScenarioProfile
from engine.state import ScenarioState

LOGGER = logging.getLogger(__name__)

ORDER_STATUS_GET_CODE = "method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()"
ORDER_STATUS_GET_NAME_BY_CODE = "method:ts-common:edu.fudan.common.entity.OrderStatus#getNameByCode(int)"
SEAT_CLASS_GET_CODE = "method:ts-common:edu.fudan.common.entity.SeatClass#getCode()"
EMPTY_FOR_NEW_USER_COLLECTIONS = frozenset({"orders"})
LAZY_LAMBDA_HOSTS = frozenset({"orElseThrow", "orElseGet"})
SEAT_CLASS_GET_NAME_BY_CODE = "method:ts-common:edu.fudan.common.entity.SeatClass#getNameByCode(int)"


@dataclass(frozen=True)
class EnumConstantIR:
    type_fqn: str
    constant: str


@dataclass(frozen=True)
class CallIR:
    file: str
    line: int
    col: int
    callee: str
    receiver: str
    kind: str  # "SAME_CLASS", "ENUM", "CONSTRUCTOR", "OTHER"
    arg_count: int
    guard: tuple[str, ...]
    enum_constant: EnumConstantIR | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CallIR:
        const_dict = d.get("enum_constant")
        enum_const = None
        if const_dict:
            enum_const = EnumConstantIR(
                type_fqn=const_dict.get("type", ""),
                constant=const_dict.get("constant", ""),
            )
        return cls(
            file=d.get("file", ""),
            line=d.get("line", 0),
            col=d.get("col", 0),
            callee=d.get("callee", ""),
            receiver=d.get("receiver", ""),
            kind=d.get("kind", "OTHER"),
            arg_count=d.get("arg_count", 0),
            guard=tuple(d.get("guard") or ()),
            enum_constant=enum_const,
        )


@dataclass(frozen=True)
class BranchIR:
    id: str
    line: int
    guard: tuple[str, ...]
    kind: str
    condition_text: str
    early_exit_then: bool
    early_exit_else: bool
    then_calls: tuple[str, ...]
    else_calls: tuple[str, ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BranchIR:
        ee = d.get("early_exit") or {}
        return cls(
            id=d.get("id", ""),
            line=d.get("line", 0),
            guard=tuple(d.get("guard") or ()),
            kind=d.get("kind", "if"),
            condition_text=d.get("condition_text", ""),
            early_exit_then=bool(ee.get("then", False)),
            early_exit_else=bool(ee.get("else", False)),
            then_calls=tuple(d.get("then_calls") or ()),
            else_calls=tuple(d.get("else_calls") or ()),
        )


@dataclass
class MethodIR:
    method_id: str
    file: str
    branches: list[BranchIR] = field(default_factory=list)
    calls: list[CallIR] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MethodIR:
        branches = [BranchIR.from_dict(b) for b in d.get("branches") or []]
        calls = [CallIR.from_dict(c) for c in d.get("calls") or []]
        return cls(
            method_id=d.get("method_id", ""),
            file=d.get("file", ""),
            branches=branches,
            calls=calls,
            unsupported=list(d.get("unsupported") or []),
        )


def find_jdk_home() -> str | None:
    """Поиск установленного JDK 17+ в стандартных путях macOS/Linux."""
    env_home = os.environ.get("JAVA_HOME")
    if env_home and Path(env_home, "bin", "java").is_file():
        return env_home

    candidates = [
        "/opt/homebrew/opt/openjdk@21",
        "/opt/homebrew/opt/openjdk@17",
        "/opt/homebrew/opt/openjdk",
        "/usr/local/opt/openjdk@21",
        "/usr/local/opt/openjdk@17",
    ]
    for c in candidates:
        if Path(c, "bin", "java").is_file():
            return c
    return None


def ensure_pool_ir(
    reparse: bool = False,
    project_root: str | Path | None = None,
) -> Path:
    """Гарантирует наличие артефакта pool_ir.json. При необходимости запускает gradle.

    Единственный источник IR — data/pool_ir.json: archparse пишет туда же, движок и скрипты читают только его.
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
    pool_ir_path = root / "data" / "pool_ir.json"

    if not reparse and pool_ir_path.is_file():
        return pool_ir_path

    # Попытка запуска Java-парсера archparse
    jdk_home = find_jdk_home()
    gradlew = root / "archparse" / "gradlew"
    if jdk_home and gradlew.is_file():
        try:
            env = os.environ.copy()
            env["JAVA_HOME"] = jdk_home
            env["PATH"] = f"{jdk_home}/bin:" + env.get("PATH", "")
            LOGGER.info("Запуск archparse gradlew для генерации pool_ir.json...")
            subprocess.run(
                [str(gradlew), "run", f"--args=--pool all -o {pool_ir_path}"],
                cwd=root / "archparse",
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception as e:
            LOGGER.warning("Не удалось запустить archparse gradle: %s", e)

    if pool_ir_path.is_file():
        return pool_ir_path

    raise FileNotFoundError(
        f"pool_ir.json не найден в {pool_ir_path}. "
        "Сгенерируйте его archparse: gradlew run --args=\"--pool all\"."
    )


class MethodPoolIR:
    """Индекс IR тел методов пула (список в archparse TargetPool)."""

    def __init__(
        self,
        methods: dict[str, MethodIR],
        branch_rules: BranchRulesRegistry | None = None,
    ) -> None:
        self.methods = methods
        self.branch_rules = branch_rules or BranchRulesRegistry.load()
        # Индекс вызовов по геометрии: (caller_method_id, line, col) -> CallIR
        self.calls_by_mid_line_col: dict[tuple[str, int, int], CallIR] = {}
        # Индекс вызовов по геометрии файла: (rel_file, line, col) -> CallIR
        self.calls_by_file_line_col: dict[tuple[str, int, int], CallIR] = {}
        # Индекс enum-вызовов по method_id: method_id -> list[CallIR]
        self.enum_calls_by_method: dict[str, list[CallIR]] = {}
        # Индекс веток по method_id: method_id -> dict[branch_id, BranchIR]
        self.branches_by_method: dict[str, dict[str, BranchIR]] = {}
        self._enum_target_cache: dict[tuple[str, str], str | None] = {}

        self._build_indexes()

    def _build_indexes(self) -> None:
        for mid, mir in self.methods.items():
            self.branches_by_method[mid] = {b.id: b for b in mir.branches}
            enum_list: list[CallIR] = []
            for c in mir.calls:
                self.calls_by_mid_line_col[(mid, c.line, c.col)] = c
                self.calls_by_file_line_col[(c.file, c.line, c.col)] = c
                if c.kind == "ENUM" and c.enum_constant:
                    enum_list.append(c)
            self.enum_calls_by_method[mid] = enum_list

    @classmethod
    def load(
        cls,
        ir_path: str | Path | None = None,
        safe: bool = True,
        branch_rules: BranchRulesRegistry | None = None,
    ) -> MethodPoolIR:
        """Загрузка pool_ir.json из файла с безопасным fallback при отсутствии."""
        try:
            path = Path(ir_path) if ir_path else ensure_pool_ir()
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            methods: dict[str, MethodIR] = {}
            for item in data:
                mir = MethodIR.from_dict(item)
                methods[mir.method_id] = mir
            return cls(methods, branch_rules=branch_rules)
        except Exception as e:
            if safe:
                LOGGER.warning("Не удалось загрузить pool_ir.json, используется пустой индекс IR: %s", e)
                return cls({}, branch_rules=branch_rules)
            raise

    def add_methods(self, items: list[dict[str, Any]]) -> None:
        """Добавление IR методов из другого артефакта archparse (конструкторы из entity_ir.json).

        Методы, которые уже есть в пуле, не перезаписываются.
        """
        added = False
        for item in items:
            mir = MethodIR.from_dict(item)
            if mir.method_id and mir.method_id not in self.methods:
                self.methods[mir.method_id] = mir
                added = True
        if added:
            self._build_indexes()

    def has_method(self, method_id: str) -> bool:
        return method_id in self.methods

    def get_enum_target(
        self, call: CallIR, skeleton_nodes: dict[str, Any] | None = None
    ) -> str | None:
        """Определение канонического метода enum в скелете для CallIR."""
        if not call.enum_constant:
            return None
        type_fqn = call.enum_constant.type_fqn
        callee = call.callee
        cache_key = (type_fqn, callee)
        if cache_key in self._enum_target_cache:
            return self._enum_target_cache[cache_key]

        target: str | None = None
        # 1. Динамический поиск по узлам скелета по FQN класса и имени метода
        if skeleton_nodes:
            pattern = f":{type_fqn}#{callee}("
            for nid, n in skeleton_nodes.items():
                if n.get("kind") == "method" and pattern in nid:
                    target = nid
                    break

        # 2. Fallback для автономных прогонов без скелета (тесты и изоляция)
        if target is None:
            if type_fqn == "edu.fudan.common.entity.OrderStatus":
                if callee == "getCode":
                    target = ORDER_STATUS_GET_CODE
                elif callee == "getNameByCode":
                    target = ORDER_STATUS_GET_NAME_BY_CODE
            elif type_fqn == "edu.fudan.common.entity.SeatClass":
                if callee == "getCode":
                    target = SEAT_CLASS_GET_CODE
                elif callee == "getNameByCode":
                    target = SEAT_CLASS_GET_NAME_BY_CODE
            elif callee == "getCode":
                target = f"method:ts-common:{type_fqn}#getCode()"
            elif callee == "getNameByCode":
                target = f"method:ts-common:{type_fqn}#getNameByCode(int)"

        self._enum_target_cache[cache_key] = target
        return target

    def evaluate_guard(
        self,
        method_id: str,
        guard: tuple[str, ...],
        profile: ScenarioProfile | None,
        scenario_state: ScenarioState | None = None,
        trace: list[str] | None = None,
    ) -> bool:
        """Оценка предикатов активации вызова (Call Guard).

        Если все предикаты guard истинны в контексте текущего сценария,
        вызов считается активным.
        Разрешение ветвей выполняется через декларативный BranchRulesRegistry (data/branch_rules.json).
        В trace (если передан) пишется, каким правилом решён каждый предикат: "<правило>@<предикат>".
        Предикаты без правила не пишутся: они проходят по умолчанию.
        """
        if not guard:
            return True
        if profile is None:
            return True

        branches = self.branches_by_method.get(method_id, {})

        for pred in guard:
            if ":" not in pred:
                continue
            bid, arm = pred.split(":", 1)

            # Плечо catch выполняется только при исключении: на штатном пути не активно (R15)
            if arm == "catch":
                if trace is not None:
                    trace.append(f"R15@{pred}")
                return False
            # Тело лямбды выполняется, только если хост-метод её вызывает (R16):
            # orElseThrow/orElseGet вызывают supplier лишь для пустого Optional
            if bid[:1] == "l" and bid[1:].isdigit():
                if arm in LAZY_LAMBDA_HOSTS:
                    if trace is not None:
                        trace.append(f"R16@{pred}")
                    return False
                continue

            # Цикл foreach исполняется, только если коллекция непуста (R17). Коллекция "orders" читается из БД
            # по аккаунту: у нового зарегистрированного пользователя заказов нет (S4)
            if bid[:1] == "f" and bid[1:].isdigit():
                if arm in EMPTY_FOR_NEW_USER_COLLECTIONS and getattr(profile, "is_new_user", False):
                    if trace is not None:
                        trace.append(f"R17@{pred}")
                    return False
                continue

            branch = branches.get(bid)
            if not branch:
                continue

            cond = branch.condition_text

            # Оценка ветвления через BranchRulesRegistry
            val, matched_rule = self.branch_rules.evaluate_branch(
                method_id=method_id,
                bid=bid,
                arm=arm,
                cond=cond,
                profile=profile,
                state=scenario_state,
            )

            if matched_rule is not None:
                if trace is not None:
                    trace.append(f"{matched_rule.id}@{pred}")
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

        return True


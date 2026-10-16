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

from engine.rules import ScenarioProfile
from engine.state import ScenarioState

LOGGER = logging.getLogger(__name__)

ORDER_STATUS_GET_CODE = "method:ts-common:edu.fudan.common.entity.OrderStatus#getCode()"
ORDER_STATUS_GET_NAME_BY_CODE = "method:ts-common:edu.fudan.common.entity.OrderStatus#getNameByCode(int)"
SEAT_CLASS_GET_CODE = "method:ts-common:edu.fudan.common.entity.SeatClass#getCode()"
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
    """Гарантирует наличие артефакта pool_ir.json. При необходимости запускает gradle."""
    root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
    primary_ir = root / "archparse" / "out" / "pool_ir.json"
    fallback_ir = root / "data" / "pool_ir.json"

    if not reparse and primary_ir.is_file():
        return primary_ir
    if not reparse and fallback_ir.is_file():
        return fallback_ir

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
                [str(gradlew), "run", "--args=--pool all"],
                cwd=root / "archparse",
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            if primary_ir.is_file():
                # Синхронизируем с data/pool_ir.json для воспроизводимости
                fallback_ir.write_bytes(primary_ir.read_bytes())
                return primary_ir
        except Exception as e:
            LOGGER.warning("Не удалось запустить archparse gradle: %s", e)

    if fallback_ir.is_file():
        return fallback_ir
    if primary_ir.is_file():
        return primary_ir

    raise FileNotFoundError(
        f"pool_ir.json не найден ни в {primary_ir}, ни в {fallback_ir}. "
        "Убедитесь, что archparse скомпилирован или скопирован в data/."
    )


class MethodPoolIR:
    """Индекс IR тел методов пула (14 ключевых методов)."""

    def __init__(self, methods: dict[str, MethodIR]) -> None:
        self.methods = methods
        # Индекс вызовов по геометрии: (caller_method_id, line, col) -> CallIR
        self.calls_by_mid_line_col: dict[tuple[str, int, int], CallIR] = {}
        # Индекс вызовов по геометрии файла: (rel_file, line, col) -> CallIR
        self.calls_by_file_line_col: dict[tuple[str, int, int], CallIR] = {}
        # Индекс enum-вызовов по method_id: method_id -> list[CallIR]
        self.enum_calls_by_method: dict[str, list[CallIR]] = {}
        # Индекс веток по method_id: method_id -> dict[branch_id, BranchIR]
        self.branches_by_method: dict[str, dict[str, BranchIR]] = {}

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
    def load(cls, ir_path: str | Path | None = None, safe: bool = True) -> MethodPoolIR:
        """Загрузка pool_ir.json из файла с безопасным fallback при отсутствии."""
        try:
            path = Path(ir_path) if ir_path else ensure_pool_ir()
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            methods: dict[str, MethodIR] = {}
            for item in data:
                mir = MethodIR.from_dict(item)
                methods[mir.method_id] = mir
            return cls(methods)
        except Exception as e:
            if safe:
                LOGGER.warning("Не удалось загрузить pool_ir.json, используется пустой индекс IR: %s", e)
                return cls({})
            raise

    def has_method(self, method_id: str) -> bool:
        return method_id in self.methods

    def get_enum_target(self, call: CallIR) -> str | None:
        """Определение канонического метода enum в скелете для CallIR."""
        if not call.enum_constant:
            return None
        type_fqn = call.enum_constant.type_fqn
        callee = call.callee
        if type_fqn == "edu.fudan.common.entity.OrderStatus":
            if callee == "getCode":
                return ORDER_STATUS_GET_CODE
            if callee == "getNameByCode":
                return ORDER_STATUS_GET_NAME_BY_CODE
        elif type_fqn == "edu.fudan.common.entity.SeatClass":
            if callee == "getCode":
                return SEAT_CLASS_GET_CODE
            if callee == "getNameByCode":
                return SEAT_CLASS_GET_NAME_BY_CODE
        return None

    def evaluate_guard(
        self,
        method_id: str,
        guard: tuple[str, ...],
        profile: ScenarioProfile | None,
        scenario_state: ScenarioState | None = None,
    ) -> bool:
        """Оценка предикатов активации вызова (Call Guard).

        Если все предикаты guard истинны в контексте текущего сценария,
        вызов считается активным.
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
            branch = branches.get(bid)
            if not branch:
                continue

            cond = branch.condition_text

            # 1. CancelServiceImpl / ExecuteServiceImpl: поезд G/D vs Regular
            # Regular ветка:
            # - в ts-cancel: b105, b178 (orderOtherResult.getStatus() == 1)
            # - в ts-execute: b65, b113 (resultFromOrder.getStatus() == 1 на втором вызове)
            if 'orderOtherResult' in cond or ("ExecuteServiceImpl" in method_id and bid in ("b65", "b113")):
                if profile.train_mode == "regular_only":
                    val = True
                elif profile.train_mode == "high_speed_only":
                    val = False
                else:
                    val = True
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False
            # High-speed ветка:
            # - в ts-cancel: b49, b160 (orderResult.getStatus() == 1)
            # - в ts-execute: b47, b95 (resultFromOrder.getStatus() == 1 на первом вызове)
            elif 'getStatus() == 1' in cond and ('orderResult' in cond or ("ExecuteServiceImpl" in method_id and bid in ("b47", "b95"))):
                if profile.train_mode == "regular_only":
                    # Для regular-поездов заказ в ts-order-service не найден (status != 1)
                    val = False
                elif profile.train_mode == "high_speed_only":
                    # Для скоростных поездов найден в ts-order-service
                    val = True
                else:
                    val = True
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 2. InsidePaymentServiceImpl#pay: G/D диспатч
            # info.getTripId().startsWith("G") || info.getTripId().startsWith("D")
            if 'startsWith("G")' in cond or 'startsWith("D")' in cond or 'tripGD' in cond:
                if profile.train_mode == "regular_only":
                    val = False
                elif profile.train_mode == "high_speed_only":
                    val = True
                else:
                    val = True
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 3. InsidePaymentServiceImpl#pay: Внешний платеж vs Баланс
            # totalExpand.compareTo(money) > 0
            if 'totalExpand.compareTo(money) > 0' in cond:
                val = getattr(profile, "has_external_payment", False)
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 4. Refused Cancel: статус собранного билета (COLLECTED) не позволяет отмену
            # order.getStatus() == OrderStatus.NOTPAID.getCode() || ...
            if 'OrderStatus.NOTPAID.getCode()' in cond and 'cancel' in method_id.lower():
                if profile.has_refused_cancel:
                    val = False
                else:
                    val = True
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 5. Refused Rebook: статус собранного билета не позволяет перебронирование
            # queryOrderResult.getData().getStatus() != 1
            if 'getStatus() != 1' in cond and 'rebook' in method_id.lower():
                if profile.has_refused_rebook:
                    val = True  #!= 1 истинно при статусе COLLECTED (2) -> ранний выход
                else:
                    val = False
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 6. PreserveServiceImpl: опция страховки
            # oti.getAssurance() == 0
            if 'getAssurance() == 0' in cond:
                val = not profile.has_assurance
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 7. PreserveServiceImpl: опция питания
            # oti.getFoodType() != 0
            if 'getFoodType() != 0' in cond:
                val = profile.has_food
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 8. PreserveServiceImpl: опция багажа
            # null != oti.getConsigneeName() && !"".equals(oti.getConsigneeName())
            if 'getConsigneeName()' in cond:
                val = profile.has_consign
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 9. ConsignServiceImpl: сменился ли вес багажа
            # originalRecord.getWeight() != consignRequest.getWeight()
            if 'getWeight()' in cond:
                val = getattr(profile, "has_consign_weight_change", False)
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 10. TokenServiceImpl#getToken: проверка кода подтверждения (verifyCode)
            # !StringUtils.isEmpty(verifyCode)
            if 'verifyCode' in cond:
                val = getattr(profile, "has_verification_code", False)
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

            # 11. UserServiceImpl#saveUser: новый пользователь vs уже существующий
            # user1 == null
            if 'user1 == null' in cond:
                val = True  # Штатный сценарий регистрации нового пользователя
                if (arm == "then" and not val) or (arm == "else" and val):
                    return False

        return True

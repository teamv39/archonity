"""Значения тела запроса и виды ссылок в StepExecutor (ADR-007, решения 2 и 6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.executor.step import StepExecutor, _context_login_blanks, _login_principal_ids
from engine.executor.values import ListV, Obj
from engine.rules import RuntimeRules

ROOT = Path(__file__).resolve().parent.parent
TARGETS_ROOT = ROOT / "hackaton" / "tt-challenge" / "targets" / "trainticket"

REGISTER = ("method:ts-user-service:user.controller.UserController#registerUser(user.dto.UserDto,"
            "org.springframework.http.HttpHeaders)")
LOGIN = ("method:ts-auth-service:auth.controller.UserController#getToken(auth.dto.BasicAuthDto,"
         "org.springframework.http.HttpHeaders)")
ADD_CONTACT = ("method:ts-contacts-service:contacts.controller.ContactsController#createNewContacts("
               "contacts.entity.Contacts,?HttpHeaders)")


@pytest.fixture(scope="module")
def executor(shared_skeleton_index):
    ex = StepExecutor(shared_skeleton_index, RuntimeRules(), ROOT / "data" / "ir", TARGETS_ROOT)
    ex.begin_scenario("T")
    return ex


class TestContextAndLogin:
    def test_login_blanks_from_context_text(self, shared_skeleton_index) -> None:
        assert _context_login_blanks(shared_skeleton_index.sk.get("context")) == {"verificationcode"}
        assert _context_login_blanks({"a": "no captcha at login; no e-mail check"}) == {"captcha"}
        assert _context_login_blanks(None) == frozenset()

    def test_login_entry_and_principal_id(self, shared_skeleton_index) -> None:
        ids = _login_principal_ids(shared_skeleton_index.N)
        assert list(ids.values()) == [("userId",)]  # @Id класса UserDetails (auth.entity.User)
        assert next(iter(ids)).split(":")[-1].startswith("auth.service.impl.TokenServiceImpl#getToken(")

    def test_login_handler_by_reachability(self, executor) -> None:
        assert executor._is_login(LOGIN)
        assert not executor._is_login(REGISTER)


class TestDtoValues:
    def test_dedupe_fields_from_read_before_save(self, executor) -> None:
        assert executor._dedupe_fields(REGISTER, "user.dto.UserDto") == ("userName",)
        assert "documentNumber" in executor._dedupe_fields(ADD_CONTACT, "contacts.entity.Contacts")
        assert executor._dedupe_fields(LOGIN, "auth.dto.BasicAuthDto") == ()

    def test_registered_name_reused_at_login(self, executor) -> None:
        executor.begin_scenario("T")
        executor._verb, executor._user_name = "POST", "passenger"
        reg = executor.build_dto("user.dto.UserDto", {"gender": 0}, {}, "current-user", REGISTER)
        assert reg.fields["userName"] not in (None, "passenger")
        assert reg.fields["userId"] is None  # свой ID новой сущности, не ID текущего пользователя
        login = executor.build_dto("auth.dto.BasicAuthDto", {}, {}, None, LOGIN)
        assert login.fields["username"] == reg.fields["userName"]
        assert login.fields["verificationCode"] == ""

    def test_login_without_registration_uses_context_passenger(self, executor) -> None:
        executor.begin_scenario("T")
        executor._verb, executor._user_name = "POST", "passenger"
        login = executor.build_dto("auth.dto.BasicAuthDto", {}, {}, None, LOGIN)
        assert login.fields["username"] == "passenger"

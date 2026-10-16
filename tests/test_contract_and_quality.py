"""Тесты аудита качества, ограничений AGENTS.md (Strict Local-First) и CLI."""
from __future__ import annotations

import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestQualityAndConstraints:
    """Аудит ограничений проекта, безопасности и производительности."""

    def test_strict_local_first_no_external_apis(self) -> None:
        """ЖЕСТКОЕ ОГРАНИЧЕНИЕ AGENTS.md: запрещены любые вызовы внешних облачных API."""
        forbidden_modules = {
            "openai",
            "anthropic",
            "google.generativeai",
            "requests",
            "urllib.request",
            "http.client",
            "httpx",
            "aiohttp",
        }

        python_files = list((ROOT / "engine").rglob("*.py")) + [ROOT / "run_eval.py"]
        for p in python_files:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in forbidden_modules, (
                            f"Violation of Strict Local-First: {p} imports forbidden '{alias.name}'"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        assert node.module not in forbidden_modules, (
                            f"Violation of Strict Local-First: {p} imports forbidden from '{node.module}'"
                        )

    def test_performance_under_5_seconds(self) -> None:
        """Тест производительности: генерация всех 8 сценариев должна укладываться в 5 секунд."""
        cmd = [sys.executable, str(ROOT / "run_eval.py"), "--no-eval"]
        t0 = time.perf_counter()
        res = subprocess.run(cmd, capture_output=True, text=True)
        duration = time.perf_counter() - t0

        assert res.returncode == 0, f"run_eval failed: {res.stderr}"
        assert duration < 5.0, f"Pipeline too slow: {duration:.2f}s (expected < 5.0s)"

    def test_cli_help(self) -> None:
        """Тестирование CLI: проверка флага --help."""
        cmd = [sys.executable, str(ROOT / "run_eval.py"), "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        assert "Archonity: генерация submission.json" in res.stdout
        assert "--skeleton" in res.stdout
        assert "--gold" in res.stdout
        assert "--rules" in res.stdout

    def test_cli_custom_output(self, tmp_path: Path) -> None:
        """Тестирование CLI: вывод в кастомный путь."""
        custom_out = tmp_path / "custom_dir" / "my_sub.json"
        cmd = [
            sys.executable,
            str(ROOT / "run_eval.py"),
            "-o", str(custom_out),
            "--no-eval",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        assert custom_out.is_file()
        assert (custom_out.parent / "canonical_graph.json").is_file()
        assert (custom_out.parent / "evidence.json").is_file()

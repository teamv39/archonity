"""Archonity Engine Package.

Экспорт ленивый: `from engine import attention` не тянет конвейер и его зависимости, поэтому `run_eval.py`
напишет выдачу и рамку ошибки, даже если конвейер не импортируется (roadmap, Р2).
"""
from typing import Any

__all__ = ["ArchonityPipeline", "RuntimeRules"]


def __getattr__(name: str) -> Any:
    if name == "ArchonityPipeline":
        from engine.pipeline import ArchonityPipeline
        return ArchonityPipeline
    if name == "RuntimeRules":
        from engine.rules import RuntimeRules
        return RuntimeRules
    raise AttributeError(f"module 'engine' has no attribute {name!r}")

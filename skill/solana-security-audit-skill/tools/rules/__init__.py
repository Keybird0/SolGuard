"""Security rules registry.

Every rule module must register its rule class via
``RuleRegistry.register`` so that :mod:`tools.solana_scan` can discover it
automatically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from core.types import Finding, Severity

if TYPE_CHECKING:
    from core.types import ParsedContract


class BaseRule(ABC):
    """Base class for all security rules."""

    id: ClassVar[str] = ""
    title: ClassVar[str] = ""
    severity: ClassVar[Severity] = Severity.INFO

    @abstractmethod
    def check(self, parsed: ParsedContract, code: str) -> list[Finding]:
        """Return findings for this rule (possibly empty)."""


class RuleRegistry:
    """Class-level registry for security rules."""

    _rules: ClassVar[dict[str, type[BaseRule]]] = {}

    @classmethod
    def register(cls, rule_cls: type[BaseRule]) -> type[BaseRule]:
        if not rule_cls.id:
            raise ValueError(f"{rule_cls.__name__} is missing a rule id")
        cls._rules[rule_cls.id] = rule_cls
        return rule_cls

    @classmethod
    def all_rules(cls) -> list[BaseRule]:
        return [rule_cls() for rule_cls in cls._rules.values()]

    @classmethod
    def get(cls, rule_id: str) -> type[BaseRule] | None:
        return cls._rules.get(rule_id)

    @classmethod
    def ids(cls) -> list[str]:
        return list(cls._rules.keys())


__all__ = ["BaseRule", "RuleRegistry"]

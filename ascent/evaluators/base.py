from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        order = ["info", "low", "medium", "high", "critical"]
        return order.index(self.value)


@dataclass
class Finding:
    severity: Severity
    source_tool: str
    rule_id: str
    message: str
    file: str | None = None
    line: int | None = None
    cve: str | None = None
    extra: dict = field(default_factory=dict)


class Scanner(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def scan(self, target: str) -> list[Finding]: ...

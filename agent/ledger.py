"""Status ledger: one row per source, online / offline / empty, plus a one-line log."""
from dataclasses import dataclass, field


@dataclass
class Row:
    label: str
    status: str = "offline"
    log: str = "Not run."


@dataclass
class Ledger:
    rows: dict[str, Row] = field(default_factory=dict)

    def add(self, key: str, label: str) -> None:
        self.rows[key] = Row(label)

    def set(self, key: str, status: str, log: str) -> None:
        assert status in ("online", "offline", "empty"), status
        self.rows[key].status = status
        self.rows[key].log = log

    def online(self, key: str) -> bool:
        return self.rows[key].status in ("online", "empty")

    def as_dict(self) -> dict:
        return {k: {"label": r.label, "status": r.status, "log": r.log} for k, r in self.rows.items()}

    def footer(self) -> str:
        return "Sources: " + " · ".join(f"{r.label} {r.status}" for r in self.rows.values())

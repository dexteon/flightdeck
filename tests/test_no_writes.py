"""Flightdeck must never become a second writer to a Hermes database.

The read layer is opened `?mode=ro` with `PRAGMA query_only=ON`, which is the runtime
guard. This is the source-level one: no mutating SQL may appear anywhere under
`hermes/`, so a future edit cannot quietly reintroduce one.

Hermes serializes its workers with `BEGIN IMMEDIATE` plus a compare-and-swap on
`tasks.status`/`claim_lock`. A writer that does not speak that protocol silently
overwrites claims. Our FTS index therefore lives in its own sidecar file, never inside a
board database.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

HERMES_PKG = Path(__file__).resolve().parents[1] / "server" / "flightdeck" / "hermes"

FORBIDDEN = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|DROP\s+TABLE|CREATE\s+TABLE|ATTACH\s+DATABASE)\b",
    re.IGNORECASE,
)

SELECT_STAR = re.compile(r"SELECT\s+\*", re.IGNORECASE)


def _sources() -> list[Path]:
    return sorted(p for p in HERMES_PKG.rglob("*.py") if p.name != "__init__.py")


def _sql_literals(path: Path) -> list[tuple[int, str]]:
    """Every string literal in the module except docstrings.

    Scanning raw lines would flag prose. The module docstring of `readdb.py` says
    'Never SELECT *' and that is documentation, not a query.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            # f-strings: join the literal parts, ignoring interpolated expressions.
            parts = [
                v.value
                for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            ]
            out.append((node.lineno, " ".join(parts)))
    return out


def test_there_are_sources_to_check() -> None:
    # A silently empty glob would make every assertion below vacuously pass.
    assert len(_sources()) >= 5


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_mutating_sql(path: Path) -> None:
    offenders = [
        f"{path.name}:{line}: {text.strip()[:90]}"
        for line, text in _sql_literals(path)
        if FORBIDDEN.search(text)
    ]
    assert not offenders, "mutating SQL in the read layer:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_select_star(path: Path) -> None:
    """`SELECT *` breaks drift tolerance: the column set differs board to board."""
    offenders = [
        f"{path.name}:{line}: {text.strip()[:90]}"
        for line, text in _sql_literals(path)
        if SELECT_STAR.search(text)
    ]
    assert not offenders, "SELECT * in the read layer:\n" + "\n".join(offenders)


def test_the_guard_actually_catches_something(tmp_path: Path) -> None:
    """A guard that cannot fail is not a guard."""
    bad = tmp_path / "bad.py"
    bad.write_text('"""Docstring mentioning SELECT * harmlessly."""\nQ = "SELECT * FROM tasks"\n')
    literals = _sql_literals(bad)

    assert [t for _, t in literals if SELECT_STAR.search(t)] == ["SELECT * FROM tasks"]

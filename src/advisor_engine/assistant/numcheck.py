"""Guardrail: every figure in a reply must come from the engine's tool output.

`verify` pulls the numbers out of the model's reply and checks each against the
numbers in the tool results. A reply number matches an allowed number when it
equals it after rounding to the precision the reply used (21.1% matches 0.2113,
because 0.2113 as a percent is 21.13).

Deliberate rules, all aimed at not letting an invented figure through:
- A figure written with % only matches the percent form (value * 100) of a tool
  value in [-1, 1]; one written like 1.19x only matches a raw tool value; a bare
  number may match either.
- Sign is ignored when matching ("a 12% loss" matches -0.12).
- The number of items in a tool list (e.g. 12 positions) counts as a tool figure.
- Numbers in error text from a tool count, since the model may quote them.
Spelled-out numbers ("twelve") are not detected.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_TOKEN = re.compile(
    rf"(?<![\w.])(?P<sign>[-−])?(?P<num>{_NUM})"
    r"(?P<suffix>\s?%|\s?percent\b|[x×](?!\w))?(?![\w]|\.\d)"
)
# "1." / "2)" / "**3.**" at the start of a line, optionally after a bullet marker.
_LIST_NUMBER = re.compile(r"^(\s*(?:[>*+-]\s+)?(?:\*\*)?)\d{1,3}[.)](?=[\s*])")
# The name of the engine's 1-in-100 stress metric is a label, not a figure.
_LABEL = re.compile(r"\b1[- ]in[- ]100\b", re.IGNORECASE)


@dataclass(frozen=True)
class Token:
    text: str
    value: float  # as written: "21.1%" -> 21.1
    decimals: int
    kind: str  # "percent" | "multiplier" | "bare"


def _tokens(text: str) -> list[Token]:
    lines = []
    for line in text.splitlines():
        line = _LIST_NUMBER.sub(lambda m: " " * len(m.group(0)), line)
        lines.append(_LABEL.sub(lambda m: " " * len(m.group(0)), line))
    out = []
    for m in _TOKEN.finditer("\n".join(lines)):
        num, suffix = m.group("num"), m.group("suffix")
        decimals = len(num.split(".")[1]) if "." in num else 0
        value = float(num.replace(",", ""))
        # A bare 4-digit integer in 1900-2100 is a year.
        if not suffix and not m.group("sign") and decimals == 0 and "," not in num \
                and len(num) == 4 and 1900 <= value <= 2100:
            continue
        if m.group("sign"):
            value = -value
        if suffix is None:
            kind = "bare"
        elif suffix.strip() in ("x", "×"):
            kind = "multiplier"
        else:
            kind = "percent"
        out.append(Token(m.group(0).strip(), value, decimals, kind))
    return out


def extract_numbers(text: str) -> list[float]:
    """Numeric values in `text`, as written (a percent keeps its percent scale)."""
    return [t.value for t in _tokens(text)]


def _walk(obj, raw: list[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            raw.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, raw)
    elif isinstance(obj, (list, tuple)):
        if obj:
            raw.append(float(len(obj)))
        for v in obj:
            _walk(v, raw)


def _collect(tool_outputs) -> tuple[list[float], list[float]]:
    raw: list[float] = []
    for out in tool_outputs:
        if isinstance(out, str):
            try:
                out = json.loads(out)
            except ValueError:
                raw.extend(extract_numbers(out))  # plain-text tool error
                continue
        _walk(out, raw)
    pct = [v * 100 for v in raw if -1 <= v <= 1]
    return raw, pct


def collect_allowed_numbers(tool_outputs) -> list[float]:
    """Every number in the tool outputs, plus the percent form of any in [-1, 1].

    `tool_outputs` is an iterable of JSON strings, parsed objects, or error text.
    """
    raw, pct = _collect(tool_outputs)
    return sorted(set(raw) | set(pct))


def _matches(tok: Token, raw: list[float], pct: list[float], rel_tol: float, abs_tol: float) -> bool:
    pools = {"percent": [pct], "multiplier": [raw], "bare": [raw, pct]}[tok.kind]
    x = abs(tok.value)
    half_unit = 0.5 * 10 ** -tok.decimals
    for pool in pools:
        for a in pool:
            a = abs(a)
            # Rounding to the reply's precision is the real test; rel/abs tol are a
            # small floor for float noise when the reply is more precise than that.
            tol = max(half_unit, min(abs_tol, rel_tol * a))
            if abs(x - a) <= tol + 1e-9:
                return True
    return False


def verify(reply_text: str, tool_outputs, rel_tol: float = 0.005, abs_tol: float = 0.0005) -> dict:
    """Check every number in the reply against the tool outputs.

    Returns {"ok": bool, "unmatched": [reply text of each failing number], "checked": int}.
    """
    raw, pct = _collect(tool_outputs)
    toks = _tokens(reply_text)
    unmatched: list[str] = []
    for t in toks:
        if not _matches(t, raw, pct, rel_tol, abs_tol) and t.text not in unmatched:
            unmatched.append(t.text)
    return {"ok": not unmatched, "unmatched": unmatched, "checked": len(toks)}

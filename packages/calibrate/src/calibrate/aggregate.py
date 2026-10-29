# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The Assess epilogue's arithmetic, in Python, for replay.

A line-for-line copy of what paperweight.md's epilogue does with the votes
once they are gathered: the mean over samples, the four inter-section rules,
the totals, the single-sample totals, the band span, the provisional line and
the verdict line. Floating-point operations run in the same order as in the
Lua, so the results are the same doubles and print the same to two decimals.
`test_parity.py` holds it to that.

It does not copy quote validation, candidate pooling, triage or sectioning.
Those decide the votes themselves, so changing them needs a full run.
`EpilogueConstants.from_prompt` reads the tunables replay can change from a
prompt; `unmodelled_changes` lists anything else that differs between two
epilogues, and replay refuses to run when that list is not empty.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass

from calibrate.shim import parse_prompt

RULES = ("top2", "corroborated", "accumulate", "max")


class EpilogueError(ValueError):
    """The epilogue cannot be read, or changed in a way replay does not model."""


# Each tunable replay models, as the pattern that finds its definition in the
# Assess epilogue. Group `v` is the value; a definition must occur once.
CONSTANT_PATTERNS = {
    "INTER_RULE": re.compile(r'^local INTER_RULE = "(?P<v>[a-z0-9_]+)"', re.M),
    "CORROBORATION": re.compile(r"^local CORROBORATION = (?P<v>\d+)", re.M),
    "STRONG": re.compile(r"^local STRONG = (?P<v>\d+(?:\.\d+)?)", re.M),
    "ACCUM_FULL": re.compile(r"^local ACCUM_FULL = (?P<v>\d+(?:\.\d+)?)", re.M),
    "EDGE_WINDOW": re.compile(r"^local EDGE_WINDOW = (?P<v>\d+(?:\.\d+)?)", re.M),
    "BINARY": re.compile(r"^local BINARY = \{(?P<v>[^}\n]*)\}", re.M),
    "LABELS": re.compile(r"^local LABELS = \{\n(?P<v>(?:[^\n]*\n)*?)\}", re.M),
}
_LABEL_ROW_RE = re.compile(r'^\s*\{ max = (?P<max>\d+),\s*label = "(?P<label>[^"]+)" \},?\s*$')
_BINARY_ITEM_RE = re.compile(r"^\s*(?P<name>[a-z_][a-z0-9_]*) = true\s*$")


def _values(code: str) -> dict[str, str]:
    out = {}
    for name, pattern in CONSTANT_PATTERNS.items():
        hits = [m.group("v") for m in pattern.finditer(code)]
        if len(hits) != 1:
            raise EpilogueError(f"{name}: {len(hits)} definitions in the Assess epilogue, expected one")
        out[name] = hits[0]
    return out


@dataclass(frozen=True)
class EpilogueConstants:
    """The tunables of the Assess epilogue that replay can change."""

    inter_rule: str
    corroboration: int
    strong: float
    accum_full: float
    edge_window: float
    binary: frozenset[str]
    labels: tuple[tuple[int, str], ...]

    @classmethod
    def from_epilogue(cls, code: str) -> EpilogueConstants:
        v = _values(code)
        if v["INTER_RULE"] not in RULES:
            raise EpilogueError(f"INTER_RULE {v['INTER_RULE']!r} is none of {RULES}")
        labels = []
        for row in v["LABELS"].splitlines():
            if not row.strip():
                continue
            m = _LABEL_ROW_RE.match(row)
            if not m:
                raise EpilogueError(f"LABELS row not understood: {row!r}")
            labels.append((int(m.group("max")), m.group("label")))
        if not labels:
            raise EpilogueError("LABELS is empty")
        binary = set()
        for item in v["BINARY"].split(","):
            if item.strip():
                m = _BINARY_ITEM_RE.match(item)
                if not m:
                    raise EpilogueError(f"BINARY entry not understood: {item!r}")
                binary.add(m.group("name"))
        return cls(inter_rule=v["INTER_RULE"], corroboration=int(v["CORROBORATION"]),
                   strong=float(v["STRONG"]), accum_full=float(v["ACCUM_FULL"]),
                   edge_window=float(v["EDGE_WINDOW"]), binary=frozenset(binary),
                   labels=tuple(labels))

    @classmethod
    def from_prompt(cls, prompt_text: str) -> EpilogueConstants:
        return cls.from_epilogue(parse_prompt(prompt_text).assess_epilogue.code)

    def to_dict(self) -> dict:
        """A JSON-ready record of the constants, for run metadata and fixtures."""
        return {
            "INTER_RULE": self.inter_rule, "CORROBORATION": self.corroboration,
            "STRONG": self.strong, "ACCUM_FULL": self.accum_full,
            "EDGE_WINDOW": self.edge_window, "BINARY": sorted(self.binary),
            "LABELS": [[top, label] for top, label in self.labels],
        }

    @classmethod
    def from_dict(cls, d: dict) -> EpilogueConstants:
        return cls(inter_rule=d["INTER_RULE"], corroboration=int(d["CORROBORATION"]),
                   strong=float(d["STRONG"]), accum_full=float(d["ACCUM_FULL"]),
                   edge_window=float(d["EDGE_WINDOW"]), binary=frozenset(d["BINARY"]),
                   labels=tuple((int(top), str(label)) for top, label in d["LABELS"]))

    def label_for(self, points: float) -> str:
        for top, label in self.labels:
            if points <= top:
                return label
        return self.labels[-1][1]

    def band_index(self, label: str) -> int:
        for i, (_, name) in enumerate(self.labels):
            if name == label:
                return i
        raise KeyError(label)

    def span_indices(self, span: str) -> tuple[int, int]:
        """A verdict span such as 'Medium to Heavy' as (lowest, highest) band index."""
        ends = span.split(" to ")
        return self.band_index(ends[0]), self.band_index(ends[-1])

    def edge_note(self, points: float) -> str:
        if points <= 0:
            return ""
        for i in range(len(self.labels) - 1):
            edge = self.labels[i][0]
            if abs(points - edge) <= self.edge_window:
                return ", close to " + (self.labels[i + 1][1] if points <= edge else self.labels[i][1])
        return ""


def patch_constants(prompt_text: str, **values: object) -> str:
    """A copy of the prompt with Assess-epilogue tunables replaced.

    Keyword names are the Lua names. `INTER_RULE` takes a rule name; numbers
    take numbers; `BINARY` takes an iterable of criterion names; `LABELS`
    takes (max, label) pairs. Everything else in the prompt is untouched.
    """
    text = prompt_text.replace("\r\n", "\n")
    layout = parse_prompt(text)
    lines = text.split("\n")
    start = sum(len(line) + 1 for line in lines[:layout.assess_epilogue.first_line - 1])
    code = layout.assess_epilogue.code
    for name, value in values.items():
        pattern = CONSTANT_PATTERNS.get(name)
        if pattern is None:
            raise EpilogueError(f"{name} is not a tunable replay models")
        hits = list(pattern.finditer(code))
        if len(hits) != 1:
            raise EpilogueError(f"{name}: {len(hits)} definitions, expected one")
        m = hits[0]
        code = code[:m.start("v")] + _lua_value(name, value) + code[m.end("v"):]
    end = start + len(layout.assess_epilogue.code)
    return text[:start] + code + text[end:]


def _lua_value(name: str, value: object) -> str:
    if name == "INTER_RULE":
        if value not in RULES:
            raise EpilogueError(f"INTER_RULE {value!r} is none of {RULES}")
        return str(value)
    if name == "BINARY":
        return " " + ", ".join(f"{n} = true" for n in value) + " " if value else ""  # type: ignore[union-attr]
    if name == "LABELS":
        rows = list(value)  # type: ignore[call-overload]
        return "".join(f'    {{ max = {top},{" " * (3 - len(str(top)))}label = "{label}" }},\n'
                       for top, label in rows)
    return repr(value) if isinstance(value, float) else str(value)


def unmodelled_changes(reference: str, candidate: str) -> list[str]:
    """Lines where two Assess epilogues differ outside the tunables replay models.

    An empty list means the candidate is the reference with only modelled
    constants changed, so replaying it is exact.
    """
    def masked(code: str) -> list[str]:
        for pattern in CONSTANT_PATTERNS.values():
            code = pattern.sub(lambda m: m.group(0)[:m.start("v") - m.start(0)] + "<tunable>", code)
        return code.split("\n")
    diff = difflib.unified_diff(masked(reference), masked(candidate), lineterm="", n=0)
    return [line for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---"))]


# --- the arithmetic ------------------------------------------------------------


def lua_mean(t: list[int]) -> float:
    if not t:
        return 0
    total = 0
    for v in t:
        total = total + v
    return total / len(t)


def rule_grade(rule: str, means: list[float], k: EpilogueConstants) -> float:
    """One criterion's grade from its section means, under one inter-section rule."""
    best, strong, total = 0, 0, 0
    ordered = []
    for m in means:
        ordered.append(m)
        if m > best:
            best = m
        if m >= k.strong:
            strong = strong + 1
        total = total + m
    ordered.sort(reverse=True)
    if rule == "max":
        return best
    if rule == "corroborated":
        if len(means) < k.corroboration:
            return best
        if strong >= k.corroboration:
            return best
        return min(best, 1)
    if rule == "accumulate":
        if len(means) < 2:
            return best
        return min(2, 2 * total / k.accum_full)
    if not ordered:
        return 0
    if len(ordered) == 1:
        return ordered[0]
    return (ordered[0] + ordered[1]) / 2


def lua_round(x: float) -> int:
    """math.floor(x + 0.5), the epilogue's rounding."""
    return math.floor(x + 0.5)


@dataclass(frozen=True)
class Aggregate:
    """What the epilogue computes from one paper's votes."""

    shorts: tuple[str, ...]
    scores: tuple[float, ...]
    shadows: dict[str, tuple[float, ...]]
    points: float
    shadow_points: dict[str, float]
    sample_totals: tuple[float, ...]
    fired: tuple[int, ...]
    strong: tuple[int, ...]
    met: int
    max_points: int
    on_threshold: tuple[str, ...]
    weight_line: str
    span: str
    provisional_line: str


def aggregate(shorts: list[str] | tuple[str, ...], votes: list[list[list[int]]], nsamples: int,
              k: EpilogueConstants) -> Aggregate:
    """`votes[c][u]` holds the sample votes of criterion c in unit u."""
    ncrit = len(shorts)
    nchunks = len(votes[0]) if votes else 0
    max_points = 2 * ncrit

    def total_from_sample(idx: int) -> float:
        t = 0
        for c in range(ncrit):
            means = []
            for u in range(nchunks):
                row = votes[c][u]
                means.append(row[idx] if idx < len(row) else 0)
            t = t + rule_grade("max" if shorts[c] in k.binary else k.inter_rule, means, k)
        return t

    scores, fired_n, strong_n = [], [], []
    shadows: dict[str, list[float]] = {r: [] for r in RULES}
    shadow_points: dict[str, float] = dict.fromkeys(RULES, 0)
    points, met = 0, 0
    for c in range(ncrit):
        means, fired, strong = [], 0, 0
        for u in range(nchunks):
            m = lua_mean(votes[c][u])
            means.append(m)
            if m > 0:
                fired = fired + 1
            if m >= k.strong:
                strong = strong + 1
        binary = shorts[c] in k.binary
        score = rule_grade("max" if binary else k.inter_rule, means, k)
        for r in RULES:
            g = rule_grade("max" if binary else r, means, k)
            shadows[r].append(g)
            shadow_points[r] = shadow_points[r] + g
        scores.append(score)
        fired_n.append(fired)
        strong_n.append(strong)
        points = points + score
        if score > 0:
            met = met + 1

    sample_totals = tuple(total_from_sample(i) for i in range(nsamples))
    reached = {k.label_for(lua_round(t)) for t in sample_totals}
    reached.add(k.label_for(lua_round(points)))
    seen = [label for _, label in k.labels if label in reached]
    span = seen[0] if len(seen) == 1 else f"{seen[0]} to {seen[-1]}" if seen else k.label_for(lua_round(points))
    return Aggregate(
        shorts=tuple(shorts), scores=tuple(scores),
        shadows={r: tuple(v) for r, v in shadows.items()}, points=points,
        shadow_points=shadow_points, sample_totals=sample_totals, fired=tuple(fired_n),
        strong=tuple(strong_n), met=met, max_points=max_points,
        on_threshold=tuple(s for s, n in zip(shorts, strong_n) if n == 1 and nchunks >= 2),
        weight_line=f"Weight: {span} ({lua_round(points)}/{max_points})", span=span,
        provisional_line=(f"Provisional: {k.label_for(points)} "
                          f"({points:.2f}/{max_points}{k.edge_note(points)})"))

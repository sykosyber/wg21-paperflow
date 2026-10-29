# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""A seeded stand-in for the Grade model: the shim's vote provider.

SYNTHETIC BY CONSTRUCTION. Nothing here is a measurement of paperweight.

The model of a paper. Every paper and criterion has a latent grade, drawn
from a per-criterion prior with `truth_seed`. The grade lives in particular
argument sections: a criterion at 2 is carried by two sections at 2, a
criterion at 1 by one section at 2 or by two sections at 1, and an
existence-asserting criterion (`implementation`) by one section at its grade.
Under the prompt's current aggregation (the mean of the two best sections,
or the max for `implementation`) those section grades come back to exactly
the latent grade, which is the paper's true grade. So a grader with no bias
and no noise reproduces the truth, and the synthetic reviewers in
`data/synthetic/` are drawn around the same truth.

A vote is `clamp(round(section grade + bias + noise), 0, 2)`, with bias and
noise per criterion from a `GraderProfile` and the noise drawn with
`noise_seed`. Bookkeeping sections (changelogs, acknowledgements,
references, wording, polls, minutes) get 0 by default. Every non-zero vote
quotes a run of words from one line of its own section, which the
epilogue's quote check accepts; `invalid_quote_rate` swaps that share of
quotes for a paraphrase the check rejects, and `missing_rate` drops replies.

Every draw has its own `random.Random`, seeded by a string that names it, so
a vote depends only on the seeds and its coordinates, never on the order
votes are asked for, and changing one criterion's bias leaves every other
criterion's votes as they were.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field

from calibrate.shim import GradeJob

# Latent grade priors per criterion, as (P(0), P(1), P(2)). They follow what
# paperweight.md's guidance says about reviewers: motivation and prior art are
# rarely 0, and insufficiency is 0 far more often than anything else.
GRADE_PRIORS: dict[str, tuple[float, float, float]] = {
    "motivation": (0.05, 0.45, 0.50),
    "audience": (0.55, 0.30, 0.15),
    "prior_art": (0.02, 0.48, 0.50),
    "vehicle": (0.35, 0.45, 0.20),
    "coordination": (0.50, 0.35, 0.15),
    "insufficiency": (0.70, 0.22, 0.08),
    "implementation": (0.25, 0.25, 0.50),
}
DEFAULT_PRIOR = (0.40, 0.40, 0.20)

# Criteria the prompt settles with the max over sections (its BINARY set).
EXISTENCE_CRITERIA = frozenset({"implementation"})

# Share of 1s carried by one section at 2 rather than by two sections at 1.
SINGLE_CARRIER_SHARE = 0.5

MAX_GRADE = 2
DEFAULT_SIGMA = 0.2
QUOTE_MIN_WORDS = 5
QUOTE_MAX_WORDS = 12
# The epilogue accepts a quote of at least this many words, and at most QUOTE_WORDS.
QUOTE_FLOOR_WORDS = 3
QUOTE_WORDS = 40

# A unit heading that names bookkeeping, as the Grade prose lists it.
BOOKKEEPING_RE = re.compile(
    r"\b(change\s*logs?|revisions?|revision history|history|acknowledge?ments?|thanks|"
    r"references|bibliography|wording|polls?|minutes)\b",
    re.IGNORECASE)

# Lua's %s: the only characters the epilogue's normalize() treats as space.
_LUA_SPACE_RE = re.compile(r"[ \t\n\v\f\r]+")

# A paraphrase no paper contains, so the epilogue rejects it as unsupported.
INVALID_QUOTE = "the paper convincingly establishes this point beyond any reasonable doubt"

REPLY_FORMAT = "SCORE: {grade}\nQUOTE: {quote}"


@dataclass(frozen=True)
class GraderProfile:
    """How a simulated grader departs from the latent truth."""

    name: str
    sigma: float = DEFAULT_SIGMA
    bias: dict[str, float] = field(default_factory=dict)
    invalid_quote_rate: float = 0.0
    missing_rate: float = 0.0
    bookkeeping_zero: bool = True
    # Criteria per paper the grader sees one grade higher than the truth, so
    # each step plants a bias of +1 on the total.
    raise_steps: int = 0
    all_zero: bool = False


PROFILES: dict[str, GraderProfile] = {
    "calibrated": GraderProfile("calibrated"),
    # The failure paperweight.md's prior-art guidance describes: a paper that
    # cites prior work throughout, read as comparing itself with it.
    "prior_art_overgrade": GraderProfile("prior_art_overgrade", bias={"prior_art": 0.8}),
    # The failure the insufficiency guidance warns about, pushed past it.
    "insufficiency_undergrade": GraderProfile(
        "insufficiency_undergrade", bias={"insufficiency": -0.8}),
    "noisy": GraderProfile("noisy", sigma=0.8),
    "all_zero": GraderProfile("all_zero", all_zero=True),
}


def _rng(*parts: object) -> random.Random:
    return random.Random("|".join(str(p) for p in parts))


def lua_words(text: str) -> list[str]:
    """Splits on exactly the characters Lua's %s matches."""
    return [w for w in _LUA_SPACE_RE.split(text) if w]


def lua_normalize(text: str) -> str:
    """paperweight.md's normalize(): ASCII lower case, whitespace collapsed."""
    lowered = text.encode("utf-8").lower().decode("utf-8", errors="replace")
    return " ".join(lua_words(lowered))


def quote_passes(quote: str, paper_text: str) -> bool:
    """Mirrors the epilogue's check on one quote, for tests and generators."""
    needle = lua_normalize(quote)
    words = needle.split(" ") if needle else []
    if not QUOTE_FLOOR_WORDS <= len(words) <= QUOTE_WORDS:
        return False
    hay = lua_normalize(paper_text)
    return needle in hay or (len(words) > 8 and " ".join(words[:8]) in hay)


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def is_bookkeeping(title: str) -> bool:
    return bool(BOOKKEEPING_RE.search(title))


def quotable_lines(chunk_text: str) -> list[list[str]]:
    """Lines of a unit's body a quote can be cut from, as Lua words.

    The first line is the heading the prologue wrote, which is not in the
    paper, and a line whose image the prologue rewrote is not either.
    """
    out = []
    for line in chunk_text.split("\n")[1:]:
        if "[image:" in line:
            continue
        words = lua_words(line)
        if len(words) >= QUOTE_FLOOR_WORDS:
            out.append(words)
    return out


def draw_grade(truth_seed: int, paper: str, short: str) -> int:
    p0, p1, _ = GRADE_PRIORS.get(short, DEFAULT_PRIOR)
    u = _rng(truth_seed, "grade", paper, short).random()
    if u < p0:
        return 0
    if u < p0 + p1:
        return 1
    return MAX_GRADE


def carriers(truth_seed: int, paper: str, short: str, grade: int,
             argument_units: list[int]) -> dict[int, int]:
    """The units that carry a criterion at `grade`, and their section grades."""
    if grade <= 0 or not argument_units:
        return {}
    rng = _rng(truth_seed, "carriers", paper, short, grade)
    units = sorted(argument_units)
    rng.shuffle(units)
    if short in EXISTENCE_CRITERIA:
        return {units[0]: grade}
    if grade >= MAX_GRADE:
        return {k: MAX_GRADE for k in units[:2]}
    if len(units) < 2 or rng.random() < SINGLE_CARRIER_SHARE:
        return {units[0]: MAX_GRADE}
    return {k: 1 for k in units[:2]}


def aggregate_sections(short: str, section_grades: list[float]) -> float:
    """The prompt's current rule: the max for existence criteria, else top2."""
    if not section_grades:
        return 0.0
    ranked = sorted(section_grades, reverse=True)
    if short in EXISTENCE_CRITERIA or len(ranked) == 1:
        return float(ranked[0])
    return (ranked[0] + ranked[1]) / 2


@dataclass(frozen=True)
class LatentPaper:
    """A paper's latent truth, given the units the prologue split it into."""

    paper: str
    argument_units: tuple[int, ...]
    sections: dict[str, dict[int, int]]
    truth: dict[str, float]

    @property
    def total(self) -> float:
        return sum(self.truth.values())


def latent_paper(truth_seed: int, paper: str, shorts: tuple[str, ...] | list[str],
                 titles: tuple[str, ...] | list[str], chunks: tuple[str, ...] | list[str],
                 raise_steps: int = 0) -> LatentPaper:
    """Builds the latent section grades and the truth they aggregate to.

    A unit carries a criterion only if it is argument, not bookkeeping, and has
    a line to quote. With `raise_steps`, that many criteria with room to rise
    (in a seeded order) are laid out one grade higher; `truth` stays unraised.
    """
    argument = [k for k, (t, c) in enumerate(zip(titles, chunks, strict=True), start=1)
                if not is_bookkeeping(t) and quotable_lines(c)]
    grades = {s: draw_grade(truth_seed, paper, s) for s in shorts}
    raised = dict(grades)
    if raise_steps:
        order = sorted(shorts)
        _rng(truth_seed, "raise", paper).shuffle(order)
        for s in [s for s in order if raised[s] < MAX_GRADE][:raise_steps]:
            raised[s] += 1
    truth, sections = {}, {}
    for s in shorts:
        true_layout = carriers(truth_seed, paper, s, grades[s], argument)
        truth[s] = aggregate_sections(s, [true_layout.get(k, 0) for k in range(1, len(titles) + 1)])
        sections[s] = carriers(truth_seed, paper, s, raised[s], argument)
    return LatentPaper(paper=paper, argument_units=tuple(argument), sections=sections, truth=truth)


class SimulatedGrader:
    """A vote provider for the shim: seeded, deterministic, independent of order."""

    def __init__(self, profile: GraderProfile, *, truth_seed: int, noise_seed: int) -> None:
        self.profile = profile
        self.truth_seed = truth_seed
        self.noise_seed = noise_seed
        self._papers: dict[str, LatentPaper] = {}
        self.invalid_quotes = 0
        self.missing = 0

    def latent(self, job: GradeJob) -> LatentPaper:
        if job.paper not in self._papers:
            self._papers[job.paper] = latent_paper(
                self.truth_seed, job.paper, job.shorts, job.titles, job.chunks,
                self.profile.raise_steps)
        return self._papers[job.paper]

    def __call__(self, job: GradeJob) -> str | None:
        p = self.profile
        rng = _rng(self.noise_seed, "vote", job.paper, job.short, job.chunk, job.sample)
        # Draw everything up front, so a vote's draws never depend on its branch.
        dropped = rng.random() < p.missing_rate
        noise = rng.gauss(0.0, p.sigma) if p.sigma > 0 else 0.0
        invalid = rng.random() < p.invalid_quote_rate
        if dropped:
            self.missing += 1
            return None
        if p.all_zero or (p.bookkeeping_zero and is_bookkeeping(job.chunk_title)):
            return REPLY_FORMAT.format(grade=0, quote="")
        lines = quotable_lines(job.chunk_text)
        base = self.latent(job).sections.get(job.short, {}).get(job.chunk, 0)
        grade = min(MAX_GRADE, max(0, round_half_up(base + p.bias.get(job.short, 0.0) + noise)))
        if grade == 0 or not lines:
            return REPLY_FORMAT.format(grade=0, quote="")
        if invalid:
            self.invalid_quotes += 1
            return REPLY_FORMAT.format(grade=grade, quote=INVALID_QUOTE)
        return REPLY_FORMAT.format(grade=grade, quote=_cut_quote(rng, lines))


def _cut_quote(rng: random.Random, lines: list[list[str]]) -> str:
    words = lines[rng.randrange(len(lines))]
    n = min(len(words), rng.randint(QUOTE_MIN_WORDS, QUOTE_MAX_WORDS))
    start = rng.randrange(len(words) - n + 1)
    return " ".join(words[start:start + n])

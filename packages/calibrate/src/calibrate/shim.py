# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Run paperweight.md's own Lua locally, with no model and no Runvil.

SYNTHETIC BY CONSTRUCTION. Everything this module produces comes from
stand-ins for the model, so no number it yields is a finding about paperweight.

What the shim does. `parse_prompt` finds the seven Lua blocks of
paperweight.md by the section each sits under (`# Paperweight`, `## Assess`,
`### Grade`, `## Analyze`) and by its position in that section, and fails
loudly if that layout changes. `run_paper` then runs them in Runvil's order:

1. the `# Paperweight` block;
2. the Assess prologue, which splits the paper and publishes it to the store;
3. the triage turn, answered by `triage_reply` (PROPOSAL unless the paper's
   front matter or id says otherwise);
4. the Assess epilogue, whose `tasks.fanout("### Grade", jobs)` runs the real
   Grade prologue and epilogue once per job, with `models.infer` answered by
   a pluggable vote provider;
5. the Analyze prologue and epilogue, with the prose turn answered by
   `ANALYZE_STUB`, so `report.md` comes out in the real format.

The Lua is Lua 5.5 (`lupa.lua55`), the version Runvil links through mlua's
`lua55` feature at the vendored commit. Lua 5.4 can be selected for a
cross-check. Each block is loaded as its own chunk with its own global table,
holding the standard-library globals a Runvil section VM keeps and the stubs
below, so a global set in one block is not visible in the next. The store is
a dict of bytes shared by every block of one run; strings cross into Lua as
raw bytes, so `#s` and `s:sub` count bytes as Runvil's do.

What the shim does NOT reproduce, so a shim run can differ from a real one:

- Runvil's Engine globals beyond the stubs. Only `store` (`read` and `write`,
  with no line bounds and no `read_numbered`), `models` (`default`, `use`,
  `infer`), `tasks` (`fanout` only), `untrusted`, `var` and `args` (the run's
  `--args` text, empty by default) exist, plus `item` inside a Grade job and
  `prose` inside an epilogue. `argv`, `call`, `compactors`, `json`, `jump`,
  `log`, `messages`, `plugins`, `prompt`, `require`, `sys`, `tools` and `ui`
  are absent, so a prompt that starts using one fails here first.
- Runvil's Engine limits: the 64 MiB Lua memory cap, the 16 MiB response
  cap, the request timeout, the tool-iteration cap and the fanout
  concurrency of 8. The shim runs fanout jobs one after another, in job
  order, and never times out.
- `untrusted` semantics. Runvil wraps the string in nonce delimiters before
  it reaches a prompt; the shim returns it unchanged. No Lua arithmetic
  depends on the wrapping, but the prose a model would see does.
- Template rendering. `{{ var.x }}` is filled by plain substitution, and no
  other template syntax is implemented. `var` is one table per section run
  (the Assess section, each Grade job, the Analyze section).
- Real model calls. Triage, every Grade vote and the Analyze prose come from
  stubs. A Grade reply is whatever the vote provider returns; `None` stands
  for a call that produced no reply, so the Grade epilogue does not run and
  the Assess epilogue counts the reply as missing.
- The Harness: no run recorder, no progress events, no gateway, no model
  binding or `models.use` options, no cancellation, and no declared-output
  check beyond reading `report.md` from the store.
- The fanout return value. Runvil returns a host object; the shim returns an
  empty table, so the epilogue's fallback (`as_string(replies[i])`) never
  supplies a reply.
- Invalid UTF-8. Lua slices strings by byte, so a heading cut mid character
  stays raw bytes in the store; the shim decodes files with replacement
  characters when it hands them back to Python.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import lupa.lua54
import lupa.lua55

DEFAULT_LUA = "5.5"
LUA_RUNTIMES = {"5.5": lupa.lua55, "5.4": lupa.lua54}

SETUP_HEADING = "# Paperweight"
ASSESS_HEADING = "## Assess"
GRADE_HEADING = "### Grade"
ANALYZE_HEADING = "## Analyze"

# How many Lua blocks each section must hold, in document order. Anything
# else means paperweight.md changed shape, and the shim refuses to guess.
EXPECTED_BLOCKS = {
    SETUP_HEADING: 1,
    ASSESS_HEADING: 2,
    GRADE_HEADING: 2,
    ANALYZE_HEADING: 2,
}

# The standard-library globals a Runvil section VM keeps (RESERVED_NAMES in
# vendor/runvil/crates/runvil-internal/lua/src/globals.rs). `_G` is rebound to
# the block's own table.
SANDBOX_GLOBALS = (
    "_VERSION", "assert", "error", "getmetatable", "ipairs", "math", "next",
    "pairs", "pcall", "select", "setmetatable", "string", "table", "tonumber",
    "tostring", "type", "xpcall",
)

PROPOSAL = "PROPOSAL"
NOT_PROPOSAL = "NOT_PROPOSAL"

# What the Analyze turn "writes". It names itself as a stand-in, so a report
# built from it can never pass for a real review.
ANALYZE_STUB = (
    "SYNTHETIC prose: the calibration shim stood in for the Analyze model "
    "turn, so this paragraph says nothing about the paper.\n\n"
    "- The verdict line above came from paperweight's own Lua, fed simulated "
    "votes.\n"
    "- No model read this paper."
)

# The smallest paper the prologue accepts, for reading the prompt's tables.
_PROBE_PAPER = "## Probe\n\nThis paper exists only so the prologue can run.\n"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_OPEN_RE = re.compile(r"^```\s*([A-Za-z0-9_+-]*)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")
_VAR_RE = re.compile(r"\{\{\s*var\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_PAPER_ID_RE = re.compile(r"^P\d+R\d+$", re.IGNORECASE)
_FRONT_FIELD_RE = re.compile(r"^([A-Za-z_-]+):\s*(.*?)\s*$")
_INFORMATIONAL_INTENTS = frozenset({"info", "inform", "informational"})

_LOADER = (
    b"function(code, name, env)\n"
    b"  local f, err = load(code, name, 't', env)\n"
    b"  if not f then error(err, 0) end\n"
    b"  return f()\n"
    b"end"
)

# store.write coerces through Lua's own tostring, so a number lands in the
# store spelled the way Lua spells it.
_STORE_TABLE = (
    b"function(read, write)\n"
    b"  return { read = read,\n"
    b"           write = function(p, v) write(p, tostring(v)) end }\n"
    b"end"
)


class PromptStructureError(ValueError):
    """paperweight.md no longer has the layout the shim was written against."""


class ShimError(RuntimeError):
    """A Lua block raised, or a stub was asked for something it cannot do."""


# --- locating the blocks ----------------------------------------------------


@dataclass(frozen=True)
class LuaBlock:
    """One fenced Lua block: its code and the 1-based lines that hold the code."""

    heading: str
    position: int
    code: str
    first_line: int
    last_line: int


@dataclass(frozen=True)
class PromptLayout:
    """The Lua blocks and prose turns of paperweight.md, located by section."""

    setup: LuaBlock
    assess_prologue: LuaBlock
    assess_epilogue: LuaBlock
    grade_prologue: LuaBlock
    grade_epilogue: LuaBlock
    analyze_prologue: LuaBlock
    analyze_epilogue: LuaBlock
    assess_prose: str
    grade_prose: str
    analyze_prose: str


def parse_prompt(text: str) -> PromptLayout:
    """Locates every Lua block by its section and position.

    Raises `PromptStructureError` unless the four sections hold exactly the
    blocks `EXPECTED_BLOCKS` names, each section appears once and in that
    order, and no Lua block sits anywhere else. The prose of a two-block
    section is the text between its prologue and its epilogue. Line numbers
    count lines of the text with CRLF read as one line break.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: dict[str, list[LuaBlock]] = {}
    prose: dict[str, list[str]] = {}
    order: list[str] = []
    heading: str | None = None
    fence: str | None = None
    fence_line = 0
    body: list[str] = []
    for i in range(_after_front_matter(lines), len(lines)):
        line = lines[i]
        if fence is not None:
            if not _FENCE_CLOSE_RE.match(line):
                body.append(line)
                continue
            if fence == "lua":
                if heading is None:
                    raise PromptStructureError(f"Lua block at line {fence_line} sits under no heading")
                found = blocks.setdefault(heading, [])
                found.append(LuaBlock(heading=heading, position=len(found) + 1,
                                      code="\n".join(body), first_line=fence_line + 1,
                                      last_line=i))
            else:
                _keep_prose(prose, blocks, heading, ["```" + fence, *body, line])
            fence = None
            continue
        opened = _FENCE_OPEN_RE.match(line)
        if opened:
            fence, fence_line, body = opened.group(1), i + 1, []
            continue
        head = _HEADING_RE.match(line)
        if head:
            heading = f"{head.group(1)} {head.group(2)}"
            order.append(heading)
            continue
        _keep_prose(prose, blocks, heading, [line])
    if fence is not None:
        raise PromptStructureError(f"code fence opened at line {fence_line} never closes")
    _check_layout(blocks, order)

    def block(heading: str, position: int) -> LuaBlock:
        return blocks[heading][position - 1]

    def turn(heading: str) -> str:
        return "\n".join(prose.get(heading, [])).strip("\n")

    return PromptLayout(
        setup=block(SETUP_HEADING, 1),
        assess_prologue=block(ASSESS_HEADING, 1),
        assess_epilogue=block(ASSESS_HEADING, 2),
        grade_prologue=block(GRADE_HEADING, 1),
        grade_epilogue=block(GRADE_HEADING, 2),
        analyze_prologue=block(ANALYZE_HEADING, 1),
        analyze_epilogue=block(ANALYZE_HEADING, 2),
        assess_prose=turn(ASSESS_HEADING),
        grade_prose=turn(GRADE_HEADING),
        analyze_prose=turn(ANALYZE_HEADING),
    )


def _after_front_matter(lines: list[str]) -> int:
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i + 1
    raise PromptStructureError("front matter opened with --- never closes")


def _keep_prose(prose: dict[str, list[str]], blocks: dict[str, list[LuaBlock]],
                heading: str | None, lines: list[str]) -> None:
    """Keeps text that sits between a section's prologue and its epilogue."""
    if heading is not None and len(blocks.get(heading, [])) == 1:
        prose.setdefault(heading, []).extend(lines)


def _check_layout(blocks: dict[str, list[LuaBlock]], order: list[str]) -> None:
    for heading, count in EXPECTED_BLOCKS.items():
        got = len(blocks.get(heading, []))
        if got != count:
            raise PromptStructureError(
                f"section {heading!r} holds {got} Lua blocks, expected {count}")
    extra = sorted(set(blocks) - set(EXPECTED_BLOCKS))
    if extra:
        raise PromptStructureError(f"Lua blocks under unexpected sections: {extra}")
    positions = []
    for heading in EXPECTED_BLOCKS:
        if order.count(heading) != 1:
            raise PromptStructureError(
                f"section {heading!r} appears {order.count(heading)} times, expected once")
        positions.append(order.index(heading))
    if positions != sorted(positions):
        raise PromptStructureError("sections out of order: expected " + ", ".join(EXPECTED_BLOCKS))


# --- stubs ---------------------------------------------------------------------


@dataclass(frozen=True)
class GradeJob:
    """One Grade fanout job, as the vote provider sees it.

    `criterion`, `chunk` and `sample` are the 1-based indices of the job
    string `c|k|s`. `chunk_text` is the unit exactly as the prologue published
    it, heading line included, and `prompt` is the Grade prose as rendered.
    `shorts`, `titles` and `chunks` describe the whole paper, so a provider
    can decide where in the paper a criterion lives.
    """

    paper: str
    criterion: int
    short: str
    chunk: int
    sample: int
    chunk_title: str
    chunk_text: str
    criterion_text: str
    prompt: str
    shorts: tuple[str, ...]
    titles: tuple[str, ...]
    chunks: tuple[str, ...]


VoteProvider = Callable[[GradeJob], "str | None"]
TriageStub = Callable[[str, str], str]


def front_matter(text: str) -> dict[str, str]:
    """Returns the scalar fields of a paper's leading YAML block, if it has one."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: dict[str, str] = {}
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = _FRONT_FIELD_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
    return out


def triage_reply(paper_id: str, paper_text: str) -> str:
    """The triage stub: PROPOSAL unless the id or the front matter says otherwise.

    A paper is NOT_PROPOSAL when its id (the one given, else the front
    matter's `document`) is not a P-number, as with N5040 or CWG1, or when its
    front matter declares an informational `intent`.
    """
    fm = front_matter(paper_text)
    pid = (paper_id or fm.get("document", "")).strip()
    if not _PAPER_ID_RE.match(pid):
        return NOT_PROPOSAL
    if fm.get("intent", "").lower() in _INFORMATIONAL_INTENTS:
        return NOT_PROPOSAL
    return PROPOSAL


# --- the Lua state -------------------------------------------------------------


def _b(s: str) -> bytes:
    return s.encode("utf-8")


def _s(b: object) -> str:
    if isinstance(b, bytes):
        return b.decode("utf-8", errors="replace")
    return str(b)


def _ignore(*_: Any) -> None:
    return None


def _no_infer(*_: Any) -> bytes:
    raise ShimError("models.infer called from a block with no prose turn")


def _constant(reply: bytes) -> Callable[..., bytes]:
    def infer(*_: Any) -> bytes:
        return reply
    return infer


class _Vm:
    """One Lua state per paper run, and the store all its blocks share."""

    def __init__(self, paper_text: str, lua_version: str, args: str = "") -> None:
        module = LUA_RUNTIMES.get(lua_version)
        if module is None:
            raise ShimError(f"Lua {lua_version} is none of {sorted(LUA_RUNTIMES)}")
        self.rt = module.LuaRuntime(encoding=None, unpack_returned_tuples=True)
        self.error_type = module.LuaError
        version = _s(self.rt.eval(b"_VERSION"))
        if version != f"Lua {lua_version}":
            raise ShimError(f"asked for Lua {lua_version}, lupa gave {version}")
        self.store: dict[bytes, bytes] = {b"paper.md": _b(paper_text)}
        self._load = self.rt.eval(_LOADER)
        self._store_table = self.rt.eval(_STORE_TABLE)(self._read, self._write)
        self._untrusted = self.rt.eval(b"function(s) return s end")
        self._stdlib = {name: self.rt.globals()[_b(name)] for name in SANDBOX_GLOBALS}
        self.tasks: Any = self.rt.table()
        self.args = _b(args)

    def _read(self, path: bytes) -> bytes:
        if path not in self.store:
            raise KeyError(f"store.read: no file {_s(path)}")
        return self.store[path]

    def _write(self, path: bytes, value: bytes) -> None:
        self.store[path] = value

    def table(self) -> Any:
        return self.rt.table()

    def env(self, var: Any, infer: Callable[..., bytes] | None = None, **extra: Any) -> Any:
        """A fresh global table for one block, holding only what Runvil gives it."""
        table = self.rt.table()
        for name, value in self._stdlib.items():
            table[_b(name)] = value
        table[b"_G"] = table
        table[b"store"] = self._store_table
        table[b"untrusted"] = self._untrusted
        table[b"tasks"] = self.tasks
        table[b"args"] = self.args
        table[b"var"] = var
        table[b"models"] = self.rt.table_from({
            b"default": _ignore,
            b"use": _ignore,
            b"infer": infer if infer is not None else _no_infer,
        })
        for name, value in extra.items():
            table[_b(name)] = value
        return table

    def run(self, block: LuaBlock, env: Any) -> None:
        name = f"{block.heading} block {block.position} (line {block.first_line})"
        try:
            self._load(_b(block.code), _b(name), env)
        except self.error_type as error:
            detail = _s(error.args[0]) if error.args else str(error)
            raise ShimError(f"{name}: {detail}") from error

    def render(self, prose: str, var: Any) -> bytes:
        """Fills `{{ var.x }}` from the Lua `var` table by plain substitution."""
        def fill(m: re.Match[str]) -> str:
            value = var[_b(m.group(1))]
            if value is None:
                raise ShimError(f"prose reads var.{m.group(1)}, which no block set")
            return _s(value)
        return _b(_VAR_RE.sub(fill, prose))

    def text(self, path: str) -> str:
        return _s(self.store.get(_b(path), b""))

    def decoded_store(self) -> dict[str, str]:
        return {_s(k): _s(v) for k, v in sorted(self.store.items())}


# --- running a paper -----------------------------------------------------------


@dataclass(frozen=True)
class PaperSplit:
    """How the Assess prologue split a paper, and the criteria it published."""

    shorts: tuple[str, ...]
    labels: tuple[str, ...]
    titles: tuple[str, ...]
    chunks: tuple[str, ...]
    samples: int
    heading_style: str


@dataclass(frozen=True)
class ShimRun:
    """What one shim run of paperweight.md left in the store."""

    paper: str
    store: dict[str, str]
    model_calls: int
    grade_jobs: int
    triage: str
    lua_version: str

    @property
    def report(self) -> str:
        return self.store.get("report.md", "")

    @property
    def diagnostics(self) -> str:
        return self.store.get("diagnostics.md", "")

    @property
    def weight(self) -> str:
        return self.store.get("weight.md", "")


def _read_split(vm: _Vm) -> PaperSplit:
    nchunks, nsamples = (int(x) for x in vm.text("pg_counts.md").split(","))
    return PaperSplit(
        shorts=tuple(vm.text("pg_shorts.md").split(",")),
        labels=tuple(vm.text("pg_labels.md").split(",")),
        titles=tuple(vm.text("pg_titles.md").split("\n")),
        chunks=tuple(vm.text(f"pg_chunk_{k}.md") for k in range(1, nchunks + 1)),
        samples=nsamples,
        heading_style=vm.text("pg_heading_style.md"),
    )


def split_paper(prompt_text: str, paper_text: str, *, lua_version: str = DEFAULT_LUA) -> PaperSplit:
    """Runs only the setup block and the Assess prologue, and reads what they published."""
    layout = parse_prompt(prompt_text)
    vm = _Vm(paper_text, lua_version)
    vm.run(layout.setup, vm.env(vm.table()))
    vm.run(layout.assess_prologue, vm.env(vm.table()))
    return _read_split(vm)


def prompt_criteria(prompt_text: str, *, lua_version: str = DEFAULT_LUA) -> tuple[str, ...]:
    """The `short` names of the prompt's CRITERIA table, in order, as its own Lua publishes them."""
    return split_paper(prompt_text, _PROBE_PAPER, lua_version=lua_version).shorts


def run_paper(prompt_text: str, paper_text: str, provider: VoteProvider, *,
              paper_id: str = "", triage: TriageStub = triage_reply,
              analyze_reply: str = ANALYZE_STUB, lua_version: str = DEFAULT_LUA,
              args: str = "") -> ShimRun:
    """Runs paperweight.md's Lua on one paper, with a stub for every model turn.

    `args` is the run's `--args` text, which Runvil hands every block as `args`.
    """
    layout = parse_prompt(prompt_text)
    vm = _Vm(paper_text, lua_version, args)
    calls = 0
    jobs_run = 0

    def answer(reply: str) -> Callable[..., bytes]:
        encoded = _b(reply)

        def infer(*_: Any) -> bytes:
            nonlocal calls
            calls += 1
            return encoded
        return infer

    vm.run(layout.setup, vm.env(vm.table()))
    assess_var = vm.table()
    vm.run(layout.assess_prologue, vm.env(assess_var))
    assess_prose = vm.render(layout.assess_prose, assess_var)
    split = _read_split(vm)
    triage_text = triage(paper_id, paper_text)

    def fanout(section: bytes, jobs: Any) -> Any:
        nonlocal calls, jobs_run
        if _s(section) != GRADE_HEADING:
            raise ShimError(f"tasks.fanout to {_s(section)!r}; the shim serves only {GRADE_HEADING!r}")
        for i in range(1, len(jobs) + 1):
            item = jobs[i]
            c, k, s = (int(x) for x in _s(item).split("|"))
            var = vm.table()
            vm.run(layout.grade_prologue, vm.env(var, item=item))
            prompt = vm.render(layout.grade_prose, var)
            reply = provider(GradeJob(
                paper=paper_id, criterion=c, short=_at(split.shorts, c), chunk=k, sample=s,
                chunk_title=_at(split.titles, k), chunk_text=vm.text(f"pg_chunk_{k}.md"),
                criterion_text=vm.text(f"pg_criterion_{c}.md"), prompt=_s(prompt),
                shorts=split.shorts, titles=split.titles, chunks=split.chunks))
            calls += 1
            jobs_run += 1
            if reply is None:
                continue
            vm.run(layout.grade_epilogue, vm.env(var, _constant(_b(reply)), item=item, prose=prompt))
        return vm.table()

    vm.tasks[b"fanout"] = fanout
    vm.run(layout.assess_epilogue, vm.env(assess_var, answer(triage_text), prose=assess_prose))
    analyze_var = vm.table()
    vm.run(layout.analyze_prologue, vm.env(analyze_var))
    analyze_prose = vm.render(layout.analyze_prose, analyze_var)
    vm.run(layout.analyze_epilogue, vm.env(analyze_var, answer(analyze_reply), prose=analyze_prose))
    return ShimRun(paper=paper_id, store=vm.decoded_store(), model_calls=calls,
                   grade_jobs=jobs_run, triage=triage_text, lua_version=lua_version)


def _at(items: tuple[str, ...], index: int) -> str:
    return items[index - 1] if 0 < index <= len(items) else ""

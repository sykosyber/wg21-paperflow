# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The Lua shim: block location, sandboxing, and a real run of paperweight.md."""

from __future__ import annotations

import re

import pytest

from calibrate import shim


def zero_votes(job: shim.GradeJob) -> str:
    return "SCORE: 0\nQUOTE: "


def first_line_votes(job: shim.GradeJob) -> str:
    """Grades 2 wherever the unit has a line of six or more words, quoting it."""
    for line in job.chunk_text.split("\n")[1:]:
        words = line.split()
        if len(words) >= 6 and "[image:" not in line:
            return "SCORE: 2\nQUOTE: " + " ".join(words[:6])
    return "SCORE: 0\nQUOTE: "


# --- locating the blocks -----------------------------------------------------


def test_blocks_are_found_by_section_and_position(prompt_text: str) -> None:
    layout = shim.parse_prompt(prompt_text)
    lines = prompt_text.split("\n")
    expected = {
        "setup": ("# Paperweight", 1, 'models.default("writer")'),
        "assess_prologue": ("## Assess", 1, "local CRITERIA = {"),
        "assess_epilogue": ("## Assess", 2, 'local INTER_RULE = "'),
        "grade_prologue": ("### Grade", 1, "var.paper_chunk = untrusted"),
        "grade_epilogue": ("### Grade", 2, 'store.write("pg_reply_"'),
        "analyze_prologue": ("## Analyze", 1, 'var.findings = untrusted(store.read("findings.md"))'),
        "analyze_epilogue": ("## Analyze", 2, 'store.write("report.md"'),
    }
    for field, (heading, position, marker) in expected.items():
        block = getattr(layout, field)
        assert (block.heading, block.position) == (heading, position), field
        assert marker in block.code, field
        # The line range is the code itself, fenced on both sides.
        assert lines[block.first_line - 2] == "```lua", field
        assert lines[block.last_line] == "```", field
        assert "\n".join(lines[block.first_line - 1:block.last_line]) == block.code, field


def test_prose_turns_sit_between_prologue_and_epilogue(prompt_text: str) -> None:
    layout = shim.parse_prompt(prompt_text)
    assert "{{ var.paper_head }}" in layout.assess_prose
    assert "`PROPOSAL` or `NOT_PROPOSAL`" in layout.assess_prose
    assert "{{ var.paper_chunk }}" in layout.grade_prose
    # The untagged fence that shows the reply format belongs to the prose.
    assert "SCORE: <0, 1 or 2>" in layout.grade_prose
    assert "{{ var.findings }}" in layout.analyze_prose
    assert "```lua" not in layout.grade_prose


def test_crlf_prompt_parses_the_same(prompt_text: str) -> None:
    lf = shim.parse_prompt(prompt_text)
    crlf = shim.parse_prompt(prompt_text.replace("\n", "\r\n"))
    assert lf == crlf


@pytest.mark.parametrize(("change", "message"), [
    (lambda t: t.replace("### Grade\n", "### Grading\n", 1), "'### Grade' holds 0"),
    (lambda t: t.replace("## Analyze\n", "## Analyze\n\n```lua\nlocal x = 1\n```\n", 1),
     "'## Analyze' holds 3"),
    (lambda t: t + "\n## Extra\n\n```lua\nlocal y = 2\n```\n", "unexpected sections"),
    (lambda t: t + "\n```lua\nlocal z = 3\n", "never closes"),
    (lambda t: t + "\n## Assess\n\nA second heading of the same name.\n", "appears 2 times"),
])
def test_layout_changes_fail_loudly(prompt_text: str, change, message: str) -> None:
    with pytest.raises(shim.PromptStructureError, match=re.escape(message)):
        shim.parse_prompt(change(prompt_text))


def test_sections_out_of_order_fail(prompt_text: str) -> None:
    layout_start = prompt_text.index("## Analyze\n")
    assess_start = prompt_text.index("## Assess\n")
    # Move the whole Analyze section ahead of Assess.
    analyze = prompt_text[layout_start:]
    reordered = prompt_text[:assess_start] + analyze + "\n" + prompt_text[assess_start:layout_start]
    with pytest.raises(shim.PromptStructureError, match="out of order"):
        shim.parse_prompt(reordered)


# --- triage stub -----------------------------------------------------------------


@pytest.mark.parametrize(("pid", "front", "expected"), [
    ("P3978R0", "", shim.PROPOSAL),
    ("N5040", "", shim.NOT_PROPOSAL),
    ("CWG1", "", shim.NOT_PROPOSAL),
    ("P4047R0", "---\ntitle: x\ndocument: P4047R0\nintent: inform\n---\n", shim.NOT_PROPOSAL),
    ("", "---\ndocument: P1234R5\n---\n", shim.PROPOSAL),
    ("", "---\ndocument: N4950\n---\n", shim.NOT_PROPOSAL),
])
def test_triage_stub(pid: str, front: str, expected: str) -> None:
    assert shim.triage_reply(pid, front + "\nbody\n") == expected


# --- running the real Lua --------------------------------------------------------


def test_a_proposal_runs_end_to_end(prompt_text: str, ideal_paper) -> None:
    run = shim.run_paper(prompt_text, ideal_paper("p3978r0"), first_line_votes, paper_id="P3978R0")
    split = shim.split_paper(prompt_text, ideal_paper("p3978r0"))
    jobs = len(split.shorts) * len(split.chunks) * split.samples
    assert run.triage == shim.PROPOSAL
    assert run.grade_jobs == jobs
    assert run.model_calls == jobs + 2  # triage and Analyze
    assert re.match(r"^Weight: \S.* \(\d+/14\)$", run.report.split("\n")[0])
    assert run.weight == run.report.split("\n")[0]
    assert shim.ANALYZE_STUB in run.report
    assert "Totals under every inter-section rule: top2 " in run.diagnostics
    assert "Replies missing: 0." in run.diagnostics
    assert "Unsupported quotes rejected: 0." in run.diagnostics
    # every Grade job left its reply where the epilogue reads it
    assert len([k for k in run.store if k.startswith("pg_reply_")]) == jobs
    assert run.lua_version == "5.5"


def test_runs_are_deterministic(prompt_text: str, ideal_paper) -> None:
    a = shim.run_paper(prompt_text, ideal_paper("p4228r0"), first_line_votes, paper_id="P4228R0")
    b = shim.run_paper(prompt_text, ideal_paper("p4228r0"), first_line_votes, paper_id="P4228R0")
    assert a.store == b.store


def test_not_a_proposal_skips_grading(prompt_text: str, ideal_paper) -> None:
    run = shim.run_paper(prompt_text, ideal_paper("n5040"), first_line_votes, paper_id="N5040")
    assert run.triage == shim.NOT_PROPOSAL
    assert run.grade_jobs == 0
    assert run.model_calls == 2
    assert run.report.startswith("Weight: n/a\n")
    assert "Classified as not a proposal; criteria not applied." in run.diagnostics


def test_missing_replies_are_counted(prompt_text: str, ideal_paper) -> None:
    seen = []

    def drop_first_three(job: shim.GradeJob) -> str | None:
        seen.append(job)
        return None if len(seen) <= 3 else zero_votes(job)

    run = shim.run_paper(prompt_text, ideal_paper("p4228r0"), drop_first_three, paper_id="P4228R0")
    assert "Replies missing: 3." in run.diagnostics


def test_unsupported_quotes_are_rejected_by_the_lua(prompt_text: str, ideal_paper) -> None:
    def invented(job: shim.GradeJob) -> str:
        if job.criterion == 1 and job.sample == 1:
            return "SCORE: 2\nQUOTE: words that appear nowhere in this paper at all"
        return zero_votes(job)

    run = shim.run_paper(prompt_text, ideal_paper("p4228r0"), invented, paper_id="P4228R0")
    split = shim.split_paper(prompt_text, ideal_paper("p4228r0"))
    assert f"Unsupported quotes rejected: {len(split.chunks)}." in run.diagnostics
    assert run.report.startswith("Weight: Weightless (0/14)")


def test_grade_jobs_see_the_rendered_prompt(prompt_text: str, ideal_paper) -> None:
    jobs: list[shim.GradeJob] = []

    def record(job: shim.GradeJob) -> str:
        jobs.append(job)
        return zero_votes(job)

    shim.run_paper(prompt_text, ideal_paper("p4228r0"), record, paper_id="P4228R0")
    first = jobs[0]
    assert (first.criterion, first.chunk, first.sample) == (1, 1, 1)
    assert first.short == "motivation"
    assert first.criterion_text in first.prompt
    assert first.chunk_text in first.prompt
    assert "{{" not in first.prompt
    assert first.chunks[first.chunk - 1] == first.chunk_text


def test_prompt_criteria_come_from_the_lua(prompt_text: str) -> None:
    assert shim.prompt_criteria(prompt_text) == (
        "motivation", "audience", "prior_art", "vehicle", "coordination",
        "insufficiency", "implementation")


def test_lua_54_and_55_agree_on_this_prompt(prompt_text: str, ideal_paper) -> None:
    a = shim.run_paper(prompt_text, ideal_paper("p0533r9"), first_line_votes,
                       paper_id="P0533R9", lua_version="5.5")
    b = shim.run_paper(prompt_text, ideal_paper("p0533r9"), first_line_votes,
                       paper_id="P0533R9", lua_version="5.4")
    assert a.store == b.store


# --- the sandbox -----------------------------------------------------------------


def _patch_setup(prompt_text: str, extra: str) -> str:
    anchor = 'models.default("writer")\n'
    assert prompt_text.count(anchor) == 1
    return prompt_text.replace(anchor, anchor + extra + "\n")


def test_only_runvil_globals_are_visible(prompt_text: str, ideal_paper) -> None:
    probe = ("assert(io == nil and os == nil and require == nil and load == nil "
             "and dofile == nil and rawget == nil and utf8 == nil)\n"
             "assert(string ~= nil and table ~= nil and math ~= nil and pcall ~= nil)\n"
             "assert(_G.store == store)")
    shim.run_paper(_patch_setup(prompt_text, probe), ideal_paper("p4228r0"), zero_votes,
                   paper_id="P4228R0")


def test_globals_do_not_survive_into_the_next_block(prompt_text: str, ideal_paper) -> None:
    leaky = _patch_setup(prompt_text, "leak = 1")
    anchor = "local SAMPLES = 3\n"
    leaky = leaky.replace(anchor, anchor + "assert(leak == nil, 'global leaked')\n", 1)
    shim.run_paper(leaky, ideal_paper("p4228r0"), zero_votes, paper_id="P4228R0")


def test_lua_errors_name_the_block(prompt_text: str, ideal_paper) -> None:
    broken = _patch_setup(prompt_text, "error('boom')")
    with pytest.raises(shim.ShimError, match=r"# Paperweight block 1 .*boom"):
        shim.run_paper(broken, ideal_paper("p4228r0"), zero_votes, paper_id="P4228R0")


def test_fanout_serves_only_grade(prompt_text: str, ideal_paper) -> None:
    rerouted = prompt_text.replace('tasks.fanout("### Grade", jobs)', 'tasks.fanout("### Other", jobs)')
    with pytest.raises(shim.ShimError, match="serves only"):
        shim.run_paper(rerouted, ideal_paper("p4228r0"), zero_votes, paper_id="P4228R0")


def test_loop_variables_are_constant_as_in_lua_55(prompt_text: str, ideal_paper) -> None:
    assigning = _patch_setup(prompt_text, "for i = 1, 2 do i = 3 end")
    with pytest.raises(shim.ShimError, match="const variable"):
        shim.run_paper(assigning, ideal_paper("p4228r0"), zero_votes, paper_id="P4228R0")

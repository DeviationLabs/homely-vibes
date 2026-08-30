"""Tests for the PR reviewer's diff rendering and output validation.

The line numbers in `__new hunk__` are the whole point of the rewrite: if they
drift, the model cites lines that do not exist and the inline-review POST fails.
So most of these assert numbering against a known new-file content.
"""

from __future__ import annotations

import re
import textwrap
import tomllib
from pathlib import Path

import pytest

from pr_review import (
    MAX_FINDINGS,
    PYPROJECT,
    Line,
    build_index,
    build_payload,
    extract_json,
    parse_diff,
    read_repo_context,
    render_diff,
    validate,
)

# A two-file diff: one edit in the middle of a file, one appended hunk. The new
# content of each file is asserted below, so the numbering has a ground truth.
TWO_FILE_DIFF = textwrap.dedent("""\
    diff --git a/pkg/alpha.py b/pkg/alpha.py
    index 1111111..2222222 100644
    --- a/pkg/alpha.py
    +++ b/pkg/alpha.py
    @@ -8,6 +8,7 @@ def head():
         one
         two
    -    old_three
    +    new_three
    +    extra_four
         five
         six
    @@ -40,3 +41,4 @@ def tail():
         forty
    +    forty_one
         forty_two
    diff --git a/pkg/beta.py b/pkg/beta.py
    index 3333333..4444444 100644
    --- a/pkg/beta.py
    +++ b/pkg/beta.py
    @@ -1,2 +1,3 @@
     import os
    +import sys
""")


def test_new_hunk_line_numbers_follow_the_new_file() -> None:
    index = build_index(parse_diff(TWO_FILE_DIFF))

    alpha = index["pkg/alpha.py"]
    # Hunk starts at new-file line 8, so: 8=one 9=two 10=new_three 11=extra_four
    assert alpha[8].text == "    one"
    assert alpha[8].added is False
    assert alpha[10].text == "    new_three"
    assert alpha[10].added is True
    assert alpha[11].text == "    extra_four"
    assert alpha[11].added is True
    # Removed lines never occupy a new-file number.
    assert all(line.text != "    old_three" for line in alpha.values())

    # Second hunk restarts numbering from its own header (+41), not from the first.
    assert alpha[41].text == "    forty"
    assert alpha[42].text == "    forty_one"
    assert alpha[42].added is True

    assert index["pkg/beta.py"][2].text == "import sys"


def test_deleted_and_binary_files_are_skipped() -> None:
    diff = textwrap.dedent("""\
        diff --git a/gone.py b/gone.py
        deleted file mode 100644
        --- a/gone.py
        +++ /dev/null
        @@ -1,2 +0,0 @@
        -import os
        -import sys
        diff --git a/logo.png b/logo.png
        index 5555555..6666666 100644
        Binary files a/logo.png and b/logo.png differ
        diff --git a/kept.py b/kept.py
        --- a/kept.py
        +++ b/kept.py
        @@ -1 +1,2 @@
         import os
        +import sys
    """)

    index = build_index(parse_diff(diff))

    assert set(index) == {"kept.py"}
    assert index["kept.py"][2].text == "import sys"


def test_rename_uses_the_new_path_and_keeps_numbering() -> None:
    diff = textwrap.dedent("""\
        diff --git a/old/name.py b/new/name.py
        similarity index 90%
        rename from old/name.py
        rename to new/name.py
        --- a/old/name.py
        +++ b/new/name.py
        @@ -5,2 +5,3 @@ def f():
             keep
        +    added
    """)

    index = build_index(parse_diff(diff))

    assert set(index) == {"new/name.py"}
    assert index["new/name.py"][6].text == "    added"


def test_render_numbers_lines_and_omits_empty_old_hunks() -> None:
    rendered = render_diff(parse_diff(TWO_FILE_DIFF))

    assert "## File: 'pkg/alpha.py'" in rendered
    assert "10 +    new_three" in rendered
    assert "8      one" in rendered
    # alpha's first hunk removes a line, so it keeps an __old hunk__ ...
    assert "-    old_three" in rendered
    # ... but beta only adds, so no __old hunk__ noise is emitted for it.
    beta = rendered.split("## File: 'pkg/beta.py'")[1]
    assert "__new hunk__" in beta
    assert "__old hunk__" not in beta


@pytest.fixture
def index() -> dict[str, dict[int, Line]]:
    return build_index(parse_diff(TWO_FILE_DIFF))


def _issue(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "path": "pkg/alpha.py",
        "line": 10,
        "existing_code": "    new_three",
        "severity": "bug",
        "confidence": 90,
        "body": "boom",
    }
    return {**base, **overrides}


# What validate() returns when nothing survives: both halves empty.
NOTHING: dict[str, list[dict[str, object]]] = {"issues": [], "notes": []}


def test_valid_issue_survives(index: dict[str, dict[int, Line]]) -> None:
    assert validate([_issue()], index) == {"issues": [_issue()], "notes": []}


def test_issue_on_a_context_line_is_dropped(index: dict[str, dict[int, Line]]) -> None:
    # Line 8 exists in the new file but this PR did not add it.
    assert validate([_issue(line=8, existing_code="    one")], index) == NOTHING


def test_hallucinated_path_is_dropped(index: dict[str, dict[int, Line]]) -> None:
    assert validate([_issue(path="src/App.tsx")], index) == NOTHING


def test_snippet_absent_from_the_file_is_dropped(index: dict[str, dict[int, Line]]) -> None:
    assert validate([_issue(existing_code="    never_written")], index) == NOTHING


def test_missing_or_unparseable_line_is_dropped(index: dict[str, dict[int, Line]]) -> None:
    assert validate([_issue(line=None)], index) == NOTHING
    assert validate([_issue(line="ten")], index) == NOTHING


def test_near_miss_line_is_snapped_not_dropped(index: dict[str, dict[int, Line]]) -> None:
    # Model said 12, the snippet actually lives on 10: repair rather than discard.
    kept = validate([_issue(line=12)], index)["issues"]

    assert [issue["line"] for issue in kept] == [10]


def test_snap_refuses_to_reach_past_the_window(index: dict[str, dict[int, Line]]) -> None:
    assert validate([_issue(line=20)], index) == NOTHING


def test_confidence_threshold_is_exclusive_below_80(index: dict[str, dict[int, Line]]) -> None:
    assert validate([_issue(confidence=79)], index) == NOTHING
    assert len(validate([_issue(confidence=80)], index)["issues"]) == 1


def test_unanchored_description_issue_becomes_a_note(index: dict[str, dict[int, Line]]) -> None:
    # A description<->diff mismatch is about the PR as a whole; forcing it onto
    # a diff line would either fake an anchor or lose the finding.
    issue = _issue(path="", line=0, existing_code="", severity="description", body="drift")

    result = validate([issue], index)

    assert result["issues"] == []
    assert result["notes"] == [{"severity": "description", "body": "drift"}]


def test_anchored_description_issue_stays_inline(index: dict[str, dict[int, Line]]) -> None:
    result = validate([_issue(severity="description")], index)

    assert [i["line"] for i in result["issues"]] == [10]
    assert result["notes"] == []


def test_unanchored_bug_is_still_dropped_not_noted(index: dict[str, dict[int, Line]]) -> None:
    # Only description findings may float free of the diff; an unanchorable
    # "bug" is a hallucinated location, same as it ever was.
    assert validate([_issue(path="", line=0, existing_code="")], index) == NOTHING


def test_low_confidence_description_issue_is_dropped(index: dict[str, dict[int, Line]]) -> None:
    issue = _issue(path="", line=0, existing_code="", severity="description", confidence=50)

    assert validate([issue], index) == NOTHING


def test_notes_count_toward_the_findings_cap(index: dict[str, dict[int, Line]]) -> None:
    floating = _issue(path="", line=0, existing_code="", severity="description")
    result = validate([dict(floating) for _ in range(MAX_FINDINGS + 5)], index)

    assert len(result["issues"]) + len(result["notes"]) == MAX_FINDINGS


def test_extract_json_ignores_chain_of_thought_around_the_object() -> None:
    content = (
        "Let me think. The nested {braces} here are a trap.\n"
        '{"issues": [{"path": "a.py", "line": 1, "body": "x"}]}\n'
        "That is my answer."
    )

    assert extract_json(content)["issues"][0]["path"] == "a.py"


def test_extract_json_raises_when_there_is_no_object() -> None:
    with pytest.raises(ValueError, match="no opening brace"):
        extract_json("I could not review this diff.")


def _declared_python() -> str:
    """The repo's own mypy baseline, read the same way read_repo_context does.

    Hardcoding the version here is what broke this file when it was ported
    between repos on different baselines — derive it so a bump can't strand it.
    """
    data = tomllib.loads(PYPROJECT.read_text())
    return str(data["tool"]["mypy"]["python_version"])


def test_repo_context_states_the_real_python_baseline() -> None:
    # Guards the PEP 758 class of false positive: the reviewer flagged
    # `except TypeError, ValueError:` as a SyntaxError because nothing told it
    # which Python this repo targets. That fact has to reach the prompt.
    context = read_repo_context()

    assert _declared_python() in context
    assert "Target Python" in context


def test_repo_context_survives_a_repo_with_no_pyproject(tmp_path: Path) -> None:
    # mastrix-ai/users is docs-only on main, its Python project still unmerged.
    # read_repo_context used to raise here, which would red the required
    # `review` check on every PR -- the reviewer fails closed, so a crash in
    # context-building is indistinguishable from "the model found nothing".
    context = read_repo_context(tmp_path / "absent" / "pyproject.toml")

    assert "No Python project" in context
    assert "Target Python" not in context


def test_payload_carries_repo_context_and_omits_response_format() -> None:
    payload, index = build_payload(TWO_FILE_DIFF, read_repo_context())

    system = payload["messages"][0]["content"]
    assert _declared_python() in system
    assert "__new hunk__" in system
    # A schema in response_format disables reasoning output on Fireworks.
    assert "response_format" not in payload
    assert payload["max_tokens"] == 65536
    assert index["pkg/alpha.py"][10].added is True


def test_pep758_syntax_is_indexed_at_the_line_it_occupies() -> None:
    # The exact shape the reviewer has repeatedly misreported: a multi-except
    # line must be indexed at the line it really occupies, whatever the syntax.
    diff = textwrap.dedent("""\
        diff --git a/mastrix/mcp_gateway/recorder.py b/mastrix/mcp_gateway/recorder.py
        --- a/mastrix/mcp_gateway/recorder.py
        +++ b/mastrix/mcp_gateway/recorder.py
        @@ -191,4 +191,5 @@ def _coerce(value):
             try:
                 return json.loads(value)
        -    except ValueError:
        +    except TypeError, ValueError:
                 return None
    """)

    index = build_index(parse_diff(diff))["mastrix/mcp_gateway/recorder.py"]

    assert index[193].text == "    except TypeError, ValueError:"
    assert index[193].added is True
    # A reviewer citing 193 with the right snippet is accepted at its real line.
    issue = {
        "path": "mastrix/mcp_gateway/recorder.py",
        "line": 193,
        "existing_code": "    except TypeError, ValueError:",
        "severity": "bug",
        "confidence": 95,
        "body": "x",
    }
    kept = validate([issue], {"mastrix/mcp_gateway/recorder.py": index})["issues"]
    assert [i["line"] for i in kept] == [193]


def test_validate_caps_findings_at_max() -> None:
    # The first live run had no cap and posted 30 comments. The cap is enforced
    # in validate(), not just requested in the prompt -- prompt caps are
    # advisory to a model that has already decided to dump its audit log.
    index = build_index(parse_diff(TWO_FILE_DIFF))
    issue = {
        "path": "pkg/alpha.py",
        "line": 10,
        "existing_code": "    new_three",
        "severity": "bug",
        "confidence": 95,
        "body": "x",
    }
    kept = validate([dict(issue) for _ in range(MAX_FINDINGS + 10)], index)["issues"]
    assert len(kept) == MAX_FINDINGS


def test_prompt_forbids_audit_log_entries_and_states_the_cap() -> None:
    # Guards the prompt-level fixes for the 30-junk-comment failure: the model
    # wrote per-line examination notes ("... No issue.") into the issues list.
    # Brittle-by-design text anchors: if someone rewrites the prompt and drops
    # these rules, that regression should fail a test, not a review.
    from pr_review import build_system_prompt, read_repo_context

    prompt = build_system_prompt(read_repo_context())
    assert "NOT a log of what you examined" in prompt
    assert f"at most {MAX_FINDINGS} issues" in prompt
    assert "be certain before flagging" in prompt.lower()


def test_extract_json_skips_a_decodable_object_that_is_not_the_review() -> None:
    # Reasoning models narrate with JSON-ish fragments before answering.
    content = (
        'Sketching the shape: {"path": "a.py", "line": 1}. Now the real answer.\n'
        '{"issues": [{"path": "b.py", "line": 2, "body": "x"}]}'
    )

    assert extract_json(content)["issues"][0]["path"] == "b.py"


def test_extract_json_raises_when_no_object_decodes() -> None:
    with pytest.raises(ValueError, match="no decodable JSON object"):
        extract_json("I considered {this} and {that} but reached no verdict.")


def test_workflow_runs_this_script_on_a_pinned_interpreter() -> None:
    # `ruff format` rewrites `except (A, B):` into the PEP 758 form, which the
    # runner's system python3 cannot parse -- it killed the review job once.
    # The interpreter has to be pinned wherever this script is invoked.
    workflow = (
        Path(__file__).resolve().parent.parent / ".github/workflows/agent-review.yml"
    ).read_text()

    # Match actual invocations (script followed by a subcommand), not prose
    # that merely mentions the file.
    invocations = [
        ln.strip()
        for ln in workflow.splitlines()
        if re.search(r"pr_review\.py (render|payload|validate)\b", ln)
    ]

    assert invocations, "workflow no longer calls pr_review.py"
    pin = f"uv run --python {_declared_python()}"
    for line in invocations:
        assert pin in line, f"interpreter not pinned to the repo baseline: {line}"


def _workflow() -> str:
    return (
        Path(__file__).resolve().parent.parent / ".github/workflows/agent-review.yml"
    ).read_text()


def test_workflow_fails_closed_when_no_review_is_produced() -> None:
    # A green `review` check must mean "reviewed", never "the reviewer gave up".
    # PR #56 merged on a green check that had posted "review skipped".
    workflow = _workflow()

    assert "if: always()" in workflow, "post step must run even if generation failed"
    # Slice to the block terminator, not to a bare "fi" -- that matches inside
    # "--body-file" and silently truncates the region under test.
    no_review = workflow.split("if [ ! -s /tmp/review.json ]; then")[1].split("\n          fi")[0]
    assert "exit 1" in no_review, "no-review branch must red the check"
    assert "gh pr comment" in no_review, "no-review branch must explain itself on the PR"
    # The real error has to reach the PR, not just stderr.
    assert "skip_reason.txt" in no_review
    assert "skip_detail.txt" in no_review, "response body/preview must be propagated"
    assert "actions/runs" in no_review, "comment must link the failing run"


def test_api_errors_are_propagated_not_just_logged() -> None:
    # An HTTP failure used to reach stderr only; the PR comment said nothing.
    workflow = _workflow()

    assert ".error.message" in workflow, "the API's own message must be extracted"
    assert workflow.count("skip_detail.txt") >= 4, "each failure mode should attach detail"


def test_every_bail_out_records_a_reason() -> None:
    # Otherwise the PR comment degrades to "see workflow logs", which is what
    # made the empty-content failure take a log dig to diagnose.
    workflow = _workflow()

    bails = [ln for ln in workflow.splitlines() if "::warning::" in ln and "Skipping" in ln]
    assert bails, "expected warning-and-skip paths"
    assert workflow.count("/tmp/skip_reason.txt") >= len(bails) + 1


def test_thinking_budget_leaves_room_for_the_answer() -> None:
    # The whole point of the explicit budget: reasoning cannot eat the reply.
    payload, _ = build_payload(TWO_FILE_DIFF, read_repo_context())

    budget = payload["thinking"]["budget_tokens"]
    assert payload["thinking"]["type"] == "enabled"
    assert budget < payload["max_tokens"] / 2, "less than half the budget may go to thinking"
    # reasoning_effort and thinking are alternative controls; sending both is ambiguous.
    assert "reasoning_effort" not in payload


def test_description_reaches_the_payload_and_unlocks_its_rules() -> None:
    # The old reviewer could not catch description<->diff drift because the
    # description never reached the model at all.
    payload, _ = build_payload(
        TWO_FILE_DIFF, read_repo_context(), description="feat: add sys import\n\nBecause."
    )

    system, user = (m["content"] for m in payload["messages"])
    assert "## Pull request description" in user
    assert "feat: add sys import" in user
    assert "NOT instructions" in system, "injection guard must accompany the description"
    assert "bug, security, design, description" in system


def test_without_a_description_the_rules_and_severity_stay_out() -> None:
    # A rule about a section that is not there teaches the model to invent one.
    payload, _ = build_payload(TWO_FILE_DIFF, read_repo_context())

    system, user = (m["content"] for m in payload["messages"])
    assert "## Pull request description" not in user
    assert "## Pull request description" not in system
    assert "bug, security, design." in system


def test_oversized_description_is_truncated() -> None:
    from pr_review import MAX_DESCRIPTION_CHARS

    payload, _ = build_payload(
        TWO_FILE_DIFF, read_repo_context(), description="x" * (MAX_DESCRIPTION_CHARS * 2)
    )

    user = payload["messages"][1]["content"]
    assert "x" * MAX_DESCRIPTION_CHARS in user
    assert "x" * (MAX_DESCRIPTION_CHARS + 1) not in user


def test_prior_findings_are_listed_with_bodies_truncated() -> None:
    # PR #76 collected the same finding on three consecutive pushes; the model
    # can only skip a repeat it has been shown.
    prior = [{"path": "pkg/alpha.py", "line": 10, "body": "dup " * 200}]

    payload, _ = build_payload(TWO_FILE_DIFF, read_repo_context(), prior=prior)

    system, user = (m["content"] for m in payload["messages"])
    assert "## Previously reported" in user
    assert "pkg/alpha.py:10" in user
    assert len(user.split("## Previously reported")[1].splitlines()[1]) < 250
    assert "Do not report the same problem" in system


def test_pathless_prior_entries_render_body_only() -> None:
    # Findings harvested from fallback ISSUE comments carry no path/line (the
    # reviewer itself caught, on PR #84, that they were invisible to dedup).
    prior = [{"body": "**[bug]** `a.py:3` — stale finding from a fallback comment"}]

    payload, _ = build_payload(TWO_FILE_DIFF, read_repo_context(), prior=prior)

    user = payload["messages"][1]["content"]
    line = user.split("## Previously reported")[1].splitlines()[1]
    assert line.startswith("- **[bug]**")
    assert "None" not in line


def test_workflow_diffs_from_the_merge_base_with_tree_fallback() -> None:
    # A concurrent PR moving main past the branch's fork point made the tree
    # diff review a revert PR #84 never touched; inline placement failed on
    # those paths and the whole review degraded to one comment.
    workflow = _workflow()

    assert "git merge-base" in workflow
    assert 'git diff "$DIFF_BASE" "$HEAD_SHA"' in workflow
    assert "falling back to tree diff" in workflow, "the fallback must announce itself"
    assert 'git diff "$BASE_SHA"' not in workflow, "no diff may bypass the merge base"


def test_workflow_feeds_fallback_issue_comments_into_dedup() -> None:
    # The inline-POST fallback posts findings via `gh pr comment` (issue
    # comments); /pulls/.../comments never returns those, so they were
    # re-flagged on every push.
    workflow = _workflow()

    assert "issues/$PR_NUMBER/comments" in workflow
    assert "pulls/$PR_NUMBER/comments" in workflow
    assert "jq -s 'add'" in workflow, "both feeds must merge into /tmp/prior.json"


def test_called_symbols_skip_builtins_keywords_and_diff_defined_names() -> None:
    from pr_review import collect_called_symbols

    diff = textwrap.dedent("""\
        diff --git a/pkg/gamma.py b/pkg/gamma.py
        --- a/pkg/gamma.py
        +++ b/pkg/gamma.py
        @@ -1,2 +1,6 @@
         def local_helper():
        +def added_helper():
        +    if enabled(record):
        +        return list_decisions(limit=5)
        +    return added_helper(len(record))
    """)

    symbols = collect_called_symbols(parse_diff(diff))

    assert "list_decisions" in symbols
    assert "enabled" in symbols
    assert "len" not in symbols, "builtins are noise"
    assert "if" not in symbols, "keywords are not calls"
    assert "added_helper" not in symbols, "defined in the diff, model can see it"


def test_signatures_come_from_the_checkout_with_location(tmp_path: Path) -> None:
    # The PR #78 failure: three findings claimed a function "requires a `path`
    # argument" that has a default. The real signature is the antidote.
    (tmp_path / "store.py").write_text(
        "def list_decisions(\n    limit: int = 100,\n    path: str | None = None,\n) -> list:\n"
        "    return []\n"
    )
    diff = textwrap.dedent("""\
        diff --git a/app.py b/app.py
        --- a/app.py
        +++ b/app.py
        @@ -1 +1,2 @@
         import store
        +rows = store.list_decisions(limit=5)
    """)

    payload, _ = build_payload(TWO_FILE_DIFF + diff, read_repo_context(), repo_root=tmp_path)

    system, user = (m["content"] for m in payload["messages"])
    assert "## Repository signatures" in user
    assert "# store.py:1" in user
    assert "path: str | None = None" in user, "the full multi-line signature must be captured"
    assert "ground truth" in system


def test_signature_pack_is_bounded(tmp_path: Path) -> None:
    from pr_review import MAX_SIGNATURE_CHARS

    for i in range(100):
        (tmp_path / f"mod{i:03}.py").write_text(f"def called_{i:03}({'x' * 200}=1):\n    pass\n")
    calls = "".join(f"+called_{i:03}(1)\n" for i in range(100))
    diff = (
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
        f"@@ -1 +1,101 @@\n import os\n{calls}"
    )

    payload, _ = build_payload(diff, read_repo_context(), repo_root=tmp_path)

    user = payload["messages"][1]["content"]
    block = user.split("## Repository signatures")[1].split("```")[1]
    assert len(block) < MAX_SIGNATURE_CHARS + 500


def test_signature_scan_skips_vendored_and_worktree_dirs(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "shadow.py").write_text("def mystery_call(wrong=1):\n    pass\n")
    diff = (
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
        "@@ -1 +1,2 @@\n import os\n+mystery_call()\n"
    )

    payload, _ = build_payload(diff, read_repo_context(), repo_root=tmp_path)

    assert "## Repository signatures" not in payload["messages"][1]["content"]


def test_linters_are_derived_from_the_pyproject_not_hardcoded() -> None:
    # This script is copied verbatim between repos on different toolchains; a
    # hardcoded linter list becomes a false suppression list the moment it
    # travels. Only recognized linters count -- pytest catches nothing by
    # existing.
    from pr_review import describe_linters

    assert (
        describe_linters(
            {
                "project": {"optional-dependencies": {"dev": ["ruff>=0.4", "pytest", "mypy"]}},
                "tool": {"codespell": {}},
            }
        )
        == "ruff, mypy and codespell"
    )
    assert describe_linters({"dependency-groups": {"dev": ["ruff"]}}) == "ruff"
    assert describe_linters({}) == ""


def test_repo_context_omits_the_linter_sentence_when_none_declared(tmp_path: Path) -> None:
    bare = tmp_path / "pyproject.toml"
    bare.write_text('[project]\nname = "bare"\nrequires-python = ">=3.12"\n')

    context = read_repo_context(bare)

    assert "Target Python" in context
    assert "CI already runs" not in context


def test_workflow_passes_description_and_prior_to_the_payload() -> None:
    workflow = _workflow()

    assert "--description /tmp/pr_desc.txt" in workflow
    assert "--prior /tmp/prior.json" in workflow
    # Title/body must travel as env vars; inline ${{ }} in run: is injectable.
    assert "PR_BODY: ${{ github.event.pull_request.body }}" in workflow
    assert '"$PR_TITLE"' in workflow


def test_workflow_names_the_model_through_one_label() -> None:
    # A model switch should touch MODEL in pr_review.py and MODEL_LABEL here,
    # nothing else -- hardcoded names in four printfs is how comments drift.
    workflow = _workflow()

    assert "MODEL_LABEL:" in workflow
    assert "DeepSeek" not in workflow
    assert workflow.count("$MODEL_LABEL") >= 4


def test_every_jq_read_of_the_response_body_is_guarded() -> None:
    # Under `set -euo pipefail` an unguarded jq on a 200 carrying non-JSON
    # kills the step before any reason is recorded, so the fail-closed comment
    # degrades to a generic message and the real error is lost.
    workflow = _workflow()

    reads = [ln for ln in workflow.splitlines() if '"$BODY" | jq' in ln]

    assert reads, "expected jq reads of the response body"
    for line in reads:
        assert "|| true" in line, f"unguarded jq read of $BODY: {line.strip()}"

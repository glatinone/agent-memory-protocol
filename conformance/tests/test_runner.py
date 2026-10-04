"""Tests for the conformance runner itself.

The vectors are checked against the reference server by the `conformance` CI
job, which boots one and runs the CLI. These tests cover the runner's own
behaviour, which those end-to-end runs would not localise.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from amp_conformance import runner

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Vector files
# ---------------------------------------------------------------------------


def test_every_vector_file_loads_and_declares_its_category():
    vectors = runner.load_vectors()
    assert set(vectors) == {
        "schema",
        "decay",
        "http_contract",
        "access_control",
        "spec_capabilities",
    }
    for category, data in vectors.items():
        assert data["cases"], f"{category} has no cases"
        ids = [case["id"] for case in data["cases"]]
        assert len(ids) == len(set(ids)), f"{category} has duplicate case ids"


def test_every_case_id_is_unique_across_the_whole_suite():
    vectors = runner.load_vectors()
    ids = [case["id"] for data in vectors.values() for case in data["cases"]]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Local categories
# ---------------------------------------------------------------------------


def test_local_categories_pass_against_the_repository_spec():
    report = runner.run(None, REPO_ROOT / "spec/v0.1.0/memory-cell.schema.json")
    assert report.failed == 0, [r.message for r in report.results if r.status == "fail"]
    assert report.count("pass") > 0


def test_a_missing_spec_is_a_skip_not_a_failure(tmp_path):
    """The suite's own fixture is missing, not the server under test failing.

    It used to report `fail`, which a third party running this suite against
    their own implementation would read as a problem with their server.
    """
    report = runner.run(None, tmp_path / "nope.json")

    assert report.failed == 0
    assert report.count("skip") == 1
    assert "no normative schema found" in report.results[0].message


def test_schema_vectors_actually_fail_when_the_document_is_wrong():
    """A vector suite that cannot fail proves nothing."""
    vectors = runner.load_vectors()
    poisoned = {"schema": {"cases": list(vectors["schema"]["cases"])}}
    poisoned["schema"]["cases"] = [
        {
            "id": "deliberately-wrong",
            "valid": False,
            "document": vectors["schema"]["cases"][0]["document"],
        }
    ]
    results = runner.check_schema(
        poisoned, REPO_ROOT / "spec/v0.1.0/memory-cell.schema.json"
    )
    assert [r.status for r in results] == ["fail"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_dotted_lookup_walks_nested_bodies():
    body = {"a": {"b": [{"c": 7}]}}
    assert runner._lookup(body, "a.b.0.c") == 7


def test_whole_value_placeholders_keep_their_type():
    captured = {"cell": {"lifecycle": {"created_at": "2025-01-01T00:00:00Z"}}}
    assert (
        runner._resolve_placeholders("{cell.lifecycle.created_at}", captured)
        == "2025-01-01T00:00:00Z"
    )


def test_partial_placeholders_are_interpolated_into_the_string():
    captured = {"cell": {"id": "mem_ABC"}}
    assert (
        runner._resolve_placeholders("/memories/{cell.id}", captured)
        == "/memories/mem_ABC"
    )


def test_placeholders_resolve_inside_nested_structures():
    captured = {"cell": {"id": "mem_ABC"}}
    body = {"path": "{cell.id}", "list": ["{cell.id}"]}
    assert runner._resolve_placeholders(body, captured) == {
        "path": "mem_ABC",
        "list": ["mem_ABC"],
    }


def test_base_url_gains_the_version_prefix_once():
    assert runner._normalize_base_url("http://h") == "http://h/amp/v1"
    assert runner._normalize_base_url("http://h/") == "http://h/amp/v1"
    assert runner._normalize_base_url("http://h/amp/v1") == "http://h/amp/v1"


# ---------------------------------------------------------------------------
# known_gap semantics
# ---------------------------------------------------------------------------


def test_a_gap_that_still_fails_is_a_gap():
    case = {"id": "x", "known_gap": "not implemented yet"}
    assert runner._result(case, "c", False, "boom").status == "known_gap"


def test_a_gap_that_starts_passing_is_flagged_for_promotion():
    case = {"id": "x", "known_gap": "not implemented yet"}
    result = runner._result(case, "c", True, "")
    assert result.status == "unexpected_pass"
    assert "fixed" in result.message


def test_a_plain_case_still_fails_plainly():
    assert runner._result({"id": "x"}, "c", False, "boom").status == "fail"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_report_counts_every_status():
    report = runner.Report()
    report.add(runner.Result("a", "c", "pass"))
    report.add(runner.Result("b", "c", "fail"))
    report.add(runner.Result("d", "c", "known_gap"))
    report.add(runner.Result("e", "c", "unexpected_pass"))
    report.add(runner.Result("f", "c", "skip"))

    summary = report.to_json()["summary"]
    assert summary == {
        "passed": 1,
        "failed": 1,
        "known_gaps": 1,
        "unexpected_passes": 1,
        "skipped": 1,
    }
    assert report.failed == 1
    # A skip is not a failure, but it is not hidden either.
    assert summary["skipped"] == 1


# ---------------------------------------------------------------------------
# End to end against a live server (skipped when none is reachable)
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("AMP_CONFORMANCE_URL", "http://127.0.0.1:8765")


def _server_is_up() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/amp/v1/health", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(
    not _server_is_up(),
    reason="no AMP server reachable; the conformance CI job boots one",
)
def test_the_reference_server_conforms():
    report = runner.run(BASE_URL, REPO_ROOT / "spec/v0.1.0/memory-cell.schema.json")
    failures = [
        f"{r.category}:{r.id} -- {r.message}"
        for r in report.results
        if r.status == "fail"
    ]
    assert not failures, failures


# ---------------------------------------------------------------------------
# Finding the normative schema
# ---------------------------------------------------------------------------


def test_the_schema_is_found_from_a_subdirectory(tmp_path):
    """A checkout run from anywhere inside itself still finds the spec."""
    from amp_conformance.runner import SPEC_RELATIVE, resolve_spec_path

    root = tmp_path / "checkout"
    (root / SPEC_RELATIVE.parent).mkdir(parents=True)
    (root / SPEC_RELATIVE).write_text("{}", encoding="utf-8")
    nested = root / "conformance" / "tests"
    nested.mkdir(parents=True)

    assert resolve_spec_path(start=nested) == root / SPEC_RELATIVE


def test_an_explicit_spec_wins(tmp_path):
    from amp_conformance.runner import resolve_spec_path

    chosen = tmp_path / "my-schema.json"
    assert resolve_spec_path(chosen, start=tmp_path) == chosen


def test_a_missing_schema_is_a_skip_and_names_the_flag(tmp_path):
    """Not a failure of the server under test: the fixture is what is missing."""
    from amp_conformance.runner import check_schema, load_vectors

    results = check_schema(load_vectors(), tmp_path / "absent.json")

    assert [r.status for r in results] == ["skip"]
    assert "--spec" in results[0].message


def test_the_packaged_copy_is_the_last_thing_tried(tmp_path, monkeypatch):
    from amp_conformance import runner

    elsewhere = tmp_path / "nowhere"
    elsewhere.mkdir()
    monkeypatch.setattr(runner, "PACKAGED_SPEC", elsewhere / "spec.json")

    assert runner.resolve_spec_path(start=elsewhere) == elsewhere / "spec.json"


def test_an_explicit_only_schema_does_not_pass_by_skipping(tmp_path):
    import amp_conformance.runner as runner

    report = runner.run(None, tmp_path / "absent.json", only={"schema"})
    assert report.count("skip") == 1

    # main() turns that into a non-zero exit; the summary alone would read green.
    assert (
        runner.main(["--spec", str(tmp_path / "absent.json"), "--only", "schema"]) == 1
    )

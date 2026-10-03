"""The conformance runner.

Usage:

    amp-conformance --base-url http://localhost:8765
    amp-conformance --base-url http://localhost:8765 --json report.json
    amp-conformance                       # local checks only (schema, decay)

The suite talks to a server over HTTP and to the specification through the JSON
Schema and the decay formula. It never imports `amp_server`, so it can be
pointed at any implementation.

A vector may carry `"known_gap": "reason"`. Such a case is reported separately
instead of counting as a failure, and a case that passes while marked a gap is
reported as `unexpected_pass` - so the gap list cannot rot in either direction.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft7Validator

VECTORS_DIR = Path(__file__).resolve().parent / "vectors"
DEFAULT_SPEC = Path("spec/v0.1.0/memory-cell.schema.json")

LOCAL_CATEGORIES = ("schema", "decay")
HTTP_CATEGORIES = ("http_contract", "access_control")

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")


@dataclass
class Result:
    """One vector's outcome."""

    id: str
    category: str
    status: str  # pass | fail | known_gap | unexpected_pass
    message: str = ""


@dataclass
class Report:
    """Collected results."""

    results: list[Result] = field(default_factory=list)

    def add(self, result: Result) -> None:
        self.results.append(result)

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def failed(self) -> int:
        return self.count("fail")

    def to_json(self) -> dict[str, Any]:
        return {
            "summary": {
                "passed": self.count("pass"),
                "failed": self.failed,
                "known_gaps": self.count("known_gap"),
                "unexpected_passes": self.count("unexpected_pass"),
            },
            "results": [
                {
                    "id": r.id,
                    "category": r.category,
                    "status": r.status,
                    "message": r.message,
                }
                for r in self.results
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data: Any = json.load(handle)
    assert isinstance(data, dict)
    return data


def load_vectors() -> dict[str, dict[str, Any]]:
    """Load every vector file, keyed by its category."""
    vectors: dict[str, dict[str, Any]] = {}
    for path in sorted(VECTORS_DIR.glob("*.json")):
        data = _load_json(path)
        vectors[data["category"]] = data
    return vectors


def _lookup(body: Any, dotted: str) -> Any:
    """Walk a dotted path into a decoded JSON body."""
    node = body
    for part in dotted.split("."):
        if isinstance(node, dict):
            node = node[part]
        elif isinstance(node, list):
            node = node[int(part)]
        else:
            raise KeyError(dotted)
    return node


def _resolve_placeholders(value: Any, captured: dict[str, Any]) -> Any:
    """Substitute {name.dotted.path} in strings, recursing through containers."""
    if isinstance(value, str):
        if value.startswith("{") and value.endswith("}") and value.count("{") == 1:
            return _lookup(captured, value[1:-1])
        return _PLACEHOLDER.sub(lambda m: str(_lookup(captured, m.group(1))), value)
    if isinstance(value, dict):
        return {k: _resolve_placeholders(v, captured) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_placeholders(v, captured) for v in value]
    return value


def _normalize_base_url(url: str) -> str:
    base = url.rstrip("/")
    return base if base.endswith("/amp/v1") else f"{base}/amp/v1"


def _result(case: dict[str, Any], category: str, ok: bool, message: str) -> Result:
    """Turn an outcome into a Result, honouring the case's known_gap marker."""
    gap = case.get("known_gap")
    if gap and ok:
        return Result(case["id"], category, "unexpected_pass", f"gap is fixed: {gap}")
    if gap:
        return Result(case["id"], category, "known_gap", f"{gap} ({message})")
    return Result(case["id"], category, "pass" if ok else "fail", message)


# ---------------------------------------------------------------------------
# Local checks
# ---------------------------------------------------------------------------


def check_schema(vectors: dict[str, Any], spec_path: Path) -> list[Result]:
    """Validate each document against the normative JSON Schema."""
    if not spec_path.exists():
        return [
            Result(
                "schema-spec-file",
                "schema",
                "fail",
                f"spec not found at {spec_path}; pass --spec",
            )
        ]
    schema = _load_json(spec_path)
    validator = Draft7Validator(schema)

    out: list[Result] = []
    for case in vectors["schema"]["cases"]:
        errors = list(validator.iter_errors(case["document"]))
        is_valid = not errors
        expected = bool(case["valid"])
        if is_valid == expected:
            out.append(_result(case, "schema", True, ""))
        else:
            detail = (
                "expected valid, schema complained: "
                + "; ".join(e.message for e in errors[:3])
                if expected
                else "expected invalid, but the document validated"
            )
            out.append(_result(case, "schema", False, detail))
    return out


def check_decay(vectors: dict[str, Any]) -> list[Result]:
    """Recompute decay scores from the specification's formula."""
    decay = vectors["decay"]
    threshold = float(decay["threshold"])
    tolerance = float(decay["tolerance"])

    out: list[Result] = []
    for case in decay["cases"]:
        score = (
            float(case["importance"])
            * float(case["confidence"])
            * math.exp(-float(case["decay_rate"]) * float(case["delta_days"]))
        )
        status = "stale" if score < threshold else "active"
        problems: list[str] = []
        if abs(score - float(case["expected_score"])) > tolerance:
            problems.append(f"score {score:.7f} != {case['expected_score']}")
        if status != case["expected_status"]:
            problems.append(f"status {status} != {case['expected_status']}")
        out.append(_result(case, "decay", not problems, "; ".join(problems)))
    return out


# ---------------------------------------------------------------------------
# HTTP checks
# ---------------------------------------------------------------------------


def check_http_contract(vectors: dict[str, Any], client: httpx.Client) -> list[Result]:
    """Run ordered request steps and assert the documented outcomes."""
    out: list[Result] = []
    for case in vectors["http_contract"]["cases"]:
        captured: dict[str, Any] = {}
        problems: list[str] = []
        for index, step in enumerate(case["steps"]):
            request = _resolve_placeholders(step["request"], captured)
            expect = step.get("expect", {})
            try:
                response = client.request(
                    request["method"],
                    request["path"],
                    headers=request.get("headers"),
                    json=request.get("json"),
                )
            except httpx.HTTPError as exc:
                problems.append(f"step {index}: request failed: {exc}")
                break

            body: Any = None
            if response.content:
                try:
                    body = response.json()
                except ValueError:
                    body = None

            if "status" in expect and response.status_code != expect["status"]:
                problems.append(
                    f"step {index}: status {response.status_code} != {expect['status']}"
                )
            if "error_code" in expect:
                actual = None
                if isinstance(body, dict):
                    actual = (body.get("error") or {}).get("code")
                if actual != expect["error_code"]:
                    wanted = expect["error_code"]
                    problems.append(
                        f"step {index}: error.code {actual!r} != {wanted!r}"
                    )
            if "has_fields" in expect:
                missing = [
                    f
                    for f in expect["has_fields"]
                    if not isinstance(body, dict) or f not in body
                ]
                if missing:
                    problems.append(f"step {index}: missing fields {missing}")
            if "id_prefix" in expect:
                value = body.get("id") if isinstance(body, dict) else None
                if not (
                    isinstance(value, str) and value.startswith(expect["id_prefix"])
                ):
                    problems.append(f"step {index}: id {value!r} lacks the prefix")
            if "json_equals" in expect:
                for dotted, wanted in expect["json_equals"].items():
                    try:
                        got = _lookup(body, dotted)
                    except (KeyError, TypeError, IndexError):
                        got = None
                    if got != wanted:
                        problems.append(
                            f"step {index}: {dotted} is {got!r}, expected {wanted!r}"
                        )

            if "capture" in step and isinstance(body, dict):
                captured[step["capture"]] = body

        out.append(_result(case, "http_contract", not problems, "; ".join(problems)))
    return out


def check_access_matrix(vectors: dict[str, Any], client: httpx.Client) -> list[Result]:
    """Check the read/write decision for every agent, on three surfaces."""
    out: list[Result] = []
    for case in vectors["access_control"]["cases"]:
        cell = case["cell"]
        creator = (cell.get("identity") or {}).get("created_by") or "agent-conformance"
        owner_id = cell["identity"]["owner_id"]
        query = case["query"]
        problems: list[str] = []

        try:
            created = client.post(
                "/memories", headers={"X-AMP-Agent-ID": creator}, json=cell
            )
        except httpx.HTTPError as exc:
            out.append(_result(case, "access_control", False, f"create failed: {exc}"))
            continue
        if created.status_code != 201:
            out.append(
                _result(
                    case,
                    "access_control",
                    False,
                    f"create returned {created.status_code}",
                )
            )
            continue
        cell_id = created.json()["id"]

        for actor in case["actors"]:
            agent = actor["agent_id"]
            headers = {"X-AMP-Agent-ID": agent}

            read = client.get(f"/memories/{cell_id}", headers=headers)
            expected_read_status = 200 if actor["read"] else 403
            if read.status_code != expected_read_status:
                problems.append(
                    f"{agent}: GET {read.status_code} != {expected_read_status}"
                )

            write = client.patch(
                f"/memories/{cell_id}",
                headers=headers,
                json={"content": {"text": cell["content"]["text"]}},
            )
            expected_write_status = 200 if actor["write"] else 403
            if write.status_code != expected_write_status:
                problems.append(
                    f"{agent}: PATCH {write.status_code} != {expected_write_status}"
                )

            search = client.post(
                "/memories/search",
                headers=headers,
                json={"query": query, "owner_id": owner_id, "limit": 10},
            )
            found = False
            if search.status_code == 200:
                found = any(
                    r.get("id") == cell_id for r in search.json().get("results", [])
                )
            if found != actor["read"]:
                problems.append(
                    f"{agent}: search found={found}, expected {actor['read']}"
                )

        out.append(_result(case, "access_control", not problems, "; ".join(problems)))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(
    base_url: str | None,
    spec_path: Path,
    only: set[str] | None = None,
    timeout: float = 10.0,
) -> Report:
    """Run every selected category and collect the results."""
    vectors = load_vectors()
    report = Report()

    def wanted(category: str) -> bool:
        return only is None or category in only

    if wanted("schema"):
        report.results.extend(check_schema(vectors, spec_path))
    if wanted("decay"):
        report.results.extend(check_decay(vectors))

    if base_url:
        with httpx.Client(
            base_url=_normalize_base_url(base_url), timeout=timeout
        ) as client:
            if wanted("http_contract"):
                report.results.extend(check_http_contract(vectors, client))
            if wanted("access_control"):
                report.results.extend(check_access_matrix(vectors, client))
    elif only is None or set(only) & set(HTTP_CATEGORIES):
        print(
            "note: --base-url not given, so the HTTP categories were skipped",
            file=sys.stderr,
        )
    return report


def _print_report(report: Report) -> None:
    for result in report.results:
        marker = {
            "pass": "ok  ",
            "fail": "FAIL",
            "known_gap": "gap ",
            "unexpected_pass": "FIXD",
        }[result.status]
        line = f"{marker} {result.category}: {result.id}"
        if result.message:
            line += f"  -- {result.message}"
        print(line)
    summary = report.to_json()["summary"]
    print(
        "\n{passed} passed, {failed} failed, {known_gaps} known gaps, "
        "{unexpected_passes} unexpected passes".format(**summary)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amp-conformance",
        description="Run the AMP conformance suite against any implementation.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL of the server under test, e.g. http://localhost:8765",
    )
    parser.add_argument(
        "--spec",
        default=str(DEFAULT_SPEC),
        help="Path to the normative JSON Schema (default: %(default)s)",
    )
    parser.add_argument(
        "--only",
        default=None,
        help=(
            "Comma-separated categories to run ("
            + ", ".join(LOCAL_CATEGORIES + HTTP_CATEGORIES)
            + ")"
        ),
    )
    parser.add_argument(
        "--json", dest="json_path", default=None, help="Write the report here"
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Per-request timeout"
    )
    args = parser.parse_args(argv)

    only = {c.strip() for c in args.only.split(",")} if args.only else None
    report = run(args.base_url, Path(args.spec), only, args.timeout)
    _print_report(report)

    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8"
        )
        print(f"report written to {args.json_path}")

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

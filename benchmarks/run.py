#!/usr/bin/env python3
"""Measure the storage paths, so the limits can be stated instead of implied.

Both backends rank the whole candidate set before slicing a page: Chroma reads the
collection, Postgres selects every matching row. That is a deliberate trade - a
decay-weighted re-rank can only lift a fresher cell above a stale one if the cell
was fetched - and it means search cost grows with collection size. This script
measures that curve instead of leaving a reader to guess.

What it measures, and what it deliberately does not:

- **Storage and ranking only.** The embedding provider is a deterministic stub, so
  a run needs no model download and the numbers describe the store, not the model.
  A real deployment's latency includes the embedding model; add it separately.
- **Single process, warm store, one machine.** Absolute numbers are only meaningful
  next to the machine they came from, which the output header records.

Usage:

    python benchmarks/run.py                       # chroma, sizes 100/1000/5000
    python benchmarks/run.py --backend postgres --dsn postgresql://...
    python benchmarks/run.py --sizes 200 --queries 5 --out docs/performance.md --append
"""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "server"))

from amp_server.embeddings import EmbeddingProvider  # noqa: E402
from amp_server.models import SearchRequest  # noqa: E402
from amp_server.storage.chroma import ChromaAdapter  # noqa: E402

OWNER = "user-bench"
AGENT = "agent-bench"
#: Words the stub embeds on, so a query has a real vector and real distances.
WORDS = ("invoice", "email", "python", "meeting", "deadline", "budget")


class StubEmbedding(EmbeddingProvider):
    """A bag of words, no model. Keeps a run offline and comparable across machines."""

    name = "benchmark-stub"
    dimensions = len(WORDS)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [float(text.lower().count(word)) for word in WORDS] or [1.0] + [0.0] * 5
            for text in texts
        ]


@dataclass
class Timing:
    """Latencies in milliseconds, and how many samples they came from.

    `best` is reported next to the distribution because a benchmark shares its
    machine with whatever else is running: the first attempt at this table showed
    a search that did not grow between 1000 and 5000 cells, until the same
    measurement with the machine quiet showed 28 ms and 67 ms. The minimum is the
    least-contended run, the median and p95 show the spread that a real deployment
    will also see.
    """

    best: float
    p50: float
    p95: float
    samples: int

    def as_cells(self) -> str:
        return f"{self.best:.1f} / {self.p50:.1f} / {self.p95:.1f}"


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


async def _time(call, samples: int) -> Timing:
    """Run `call` `samples` times and report the distribution.

    The first call is discarded: it pays for lazily-built indexes and a cold
    connection, which is a property of the run and not of the store.
    """
    timings: list[float] = []
    for index in range(samples + 1):
        started = time.perf_counter()
        await call(index)
        elapsed = (time.perf_counter() - started) * 1000
        if index:
            timings.append(elapsed)
    return Timing(
        best=min(timings),
        p50=statistics.median(timings),
        p95=_percentile(timings, 0.95),
        samples=samples,
    )


def build_cell(index: int):
    from amp_server.models import (
        LifecycleStatus,
        MemoryAccessPolicy,
        MemoryCell,
        MemoryContent,
        MemoryIdentity,
        MemoryLifecycle,
        MemoryScoring,
        MemoryType,
        OwnerType,
    )

    word = WORDS[index % len(WORDS)]
    return MemoryCell(
        type=MemoryType.SEMANTIC,
        content=MemoryContent(text=f"{word} note number {index}"),
        identity=MemoryIdentity(
            owner_id=OWNER, owner_type=OwnerType.USER, created_by=AGENT
        ),
        lifecycle=MemoryLifecycle(
            created_at=datetime.now(UTC), status=LifecycleStatus.ACTIVE
        ),
        scoring=MemoryScoring(),
        access_policy=MemoryAccessPolicy(readable_by=[AGENT]),
    )


async def measure(storage, size: int, queries: int, query: str) -> dict[str, object]:
    """Ingest `size` cells, then time search, get and a first page of listing."""
    ingest_started = time.perf_counter()
    ids: list[str] = []
    for index in range(size):
        ids.append(await storage.save(build_cell(index)))
    ingest_seconds = time.perf_counter() - ingest_started

    def search_call(index: int):
        # The same query every sample. Rotating through words measures six different
        # operations and reports the spread between them as if it were the spread of
        # one - which produced a table where a search over 5000 cells looked faster
        # than the same search over 1000.
        request = SearchRequest(query=query, owner_id=OWNER, limit=10)
        return storage.search(request, agent_id=AGENT)

    def get_call(index: int):
        return storage.get(ids[index % len(ids)])

    def list_call(index: int):
        return storage.query(
            owner_id=OWNER, types=None, status=None, limit=20, offset=0
        )

    return {
        "cells": size,
        "ingest_per_second": size / ingest_seconds if ingest_seconds else float("inf"),
        "search": await _time(search_call, queries),
        "get": await _time(get_call, queries),
        "list_page": await _time(list_call, queries),
    }


async def run(args: argparse.Namespace) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for size in args.sizes:
        if args.backend == "postgres":
            from amp_server.storage.postgres import PostgresAdapter

            dsn = args.dsn or os.environ.get("AMP_TEST_POSTGRES_DSN")
            if not dsn:
                raise SystemExit(
                    "postgres needs --dsn or AMP_TEST_POSTGRES_DSN; this is the same "
                    "variable the storage tests use"
                )
            table = f"amp_bench_{int(time.time())}"
            storage = PostgresAdapter(
                dsn=dsn, table=table, embedding_provider=StubEmbedding()
            )
            try:
                results.append(await measure(storage, size, args.queries, args.query))
            finally:
                with storage._connection.cursor() as cursor:
                    cursor.execute(f"DROP TABLE IF EXISTS {table}")
                storage.close()
            continue

        storage = ChromaAdapter(
            collection_name=f"bench_{int(time.time())}_{size}",
            embedding_provider=StubEmbedding(),
        )
        results.append(await measure(storage, size, args.queries, args.query))
    return results


def render(results: list[dict[str, object]], args: argparse.Namespace) -> str:
    """A markdown table, a header naming the machine, and the two known limits."""
    lines = [
        f"### {args.backend}",
        "",
        f"- Machine: {platform.system()} {platform.release()}, "
        f"{platform.machine()}, {os.cpu_count()} CPUs, "
        f"Python {platform.python_version()}",
        f"- Embeddings: {StubEmbedding().name} "
        "(a stub, so these numbers exclude the model)",
        f"- Queries per measurement: {args.queries} of the same query "
        f"({args.query!r}), first call discarded",
        "- Columns are min / median / p95 over those samples: the minimum is the "
        "least-contended run",
        f"- Run: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        "",
        "| Cells | Ingest (cells/s) | Search min / p50 / p95 (ms) | "
        "GET min / p50 / p95 (ms) | List page min / p50 / p95 (ms) |",
        "|---|---|---|---|---|",
    ]
    for row in results:
        search, get, listing = row["search"], row["get"], row["list_page"]
        lines.append(
            f"| {row['cells']} | {row['ingest_per_second']:.0f} | "
            f"{search.as_cells()} | {get.as_cells()} | {listing.as_cells()} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=("chroma", "postgres"), default="chroma")
    parser.add_argument(
        "--dsn", default=None, help="postgres DSN (or AMP_TEST_POSTGRES_DSN)"
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=[100, 1000, 5000],
        help="collection sizes to measure, in order",
    )
    parser.add_argument(
        "--queries", type=int, default=20, help="samples per measurement"
    )
    parser.add_argument(
        "--query",
        default=WORDS[0],
        help="the search term every sample uses, so one operation is measured",
    )
    parser.add_argument("--out", type=Path, default=None, help="write the table here")
    parser.add_argument(
        "--append",
        action="store_true",
        help="append to --out instead of overwriting it",
    )
    args = parser.parse_args()

    table = render(asyncio.run(run(args)), args)
    print(table)
    if args.out:
        existing = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        separator = "\n\n" if existing and args.append else ""
        body = (existing + separator) if args.append else ""
        args.out.write_text(body + table + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

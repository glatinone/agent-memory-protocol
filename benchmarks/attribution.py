"""Ad-hoc cost attribution: which part of a search grows with collection size.

Not part of the published harness. It exists to answer one question the published
numbers raised - search latency barely moved from 1000 to 5000 cells while the
listing path grew linearly - so the explanation in docs/performance.md is measured
rather than guessed.
"""

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(REPO / "benchmarks"))

from amp_server.models import SearchRequest  # noqa: E402
from amp_server.storage.chroma import ChromaAdapter  # noqa: E402
from run import AGENT, OWNER, StubEmbedding, build_cell  # noqa: E402


def best_sync(fn: Callable[[], object], repeat: int = 7) -> float:
    times = []
    for _ in range(repeat):
        started = time.perf_counter()
        fn()
        times.append((time.perf_counter() - started) * 1000)
    return min(times)


async def best_async(fn: Callable[[], Awaitable[object]], repeat: int = 7) -> float:
    times = []
    for _ in range(repeat):
        started = time.perf_counter()
        await fn()
        times.append((time.perf_counter() - started) * 1000)
    return min(times)


async def probe(size: int) -> None:
    provider = StubEmbedding()
    storage = ChromaAdapter(
        collection_name=f"cost_probe_{size}", embedding_provider=provider
    )
    for index in range(size):
        await storage.save(build_cell(index))

    request = SearchRequest(query="invoice", owner_id=OWNER, limit=10)
    embedded = storage._embed(["invoice"])

    def chroma_fetch() -> None:
        """The collection read the adapter does, before any Python work on it."""
        storage._collection.query(
            query_embeddings=embedded,
            n_results=size,
            include=["metadatas", "distances"],
        )

    chroma_ms = best_sync(chroma_fetch)
    search_ms = await best_async(lambda: storage.search(request, agent_id=AGENT))
    list_ms = await best_async(
        lambda: storage.query(
            owner_id=OWNER, types=None, status=None, limit=20, offset=0
        )
    )

    print(
        f"N={size:>5}  chroma fetch {chroma_ms:7.1f} ms | "
        f"adapter search {search_ms:7.1f} ms | listing page {list_ms:7.1f} ms"
    )


for size in (100, 1000, 5000):
    asyncio.run(probe(size))

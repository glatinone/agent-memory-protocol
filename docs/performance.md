# Performance

Two limits shape every number on this page, and both are deliberate:

- **Search ranks the whole candidate set before cutting a page.** Chroma reads the
  collection; Postgres selects every row matching the filters. A decay-weighted
  re-rank can only lift a fresher cell above a stale one if that cell was actually
  fetched, so the ranking cannot happen inside the index. The cost is a search whose
  latency grows with how much is stored, not with how much you asked for.
- **The access filter cannot be pushed into either store.** `readable_by` holds
  patterns rather than ids, so every candidate is checked in Python. That is also why
  `limit` on the listing and search endpoints counts cells the caller may read rather
  than cells examined.

Both are the price of ranking by relevance and enforcing per-cell access, and both
are the reason a large collection wants the Postgres backend and a real deployment
wants a cache in front. A vector store with a narrower job (top-k similarity only,
no per-cell policy) will beat this on search latency; that is a different feature set,
not a faster version of this one.

## Measured numbers

`benchmarks/run.py` produces these. It uses a deterministic stub embedding, so a run
needs no model download and the numbers describe the store and the ranking path -
**not** the embedding model, which in a real deployment dominates latency.

### chroma

- Machine: Windows 11, AMD64, 12 CPUs, Python 3.12.10
- Embeddings: benchmark-stub (a stub, so these numbers exclude the model)
- Queries per measurement: 20 of the same query ('invoice'), first call discarded
- Columns are min / median / p95 over those samples: the minimum is the least-contended run
- Run: 2026-10-04 09:15 UTC

| Cells | Ingest (cells/s) | Search min / p50 / p95 (ms) | GET min / p50 / p95 (ms) | List page min / p50 / p95 (ms) |
|---|---|---|---|---|
| 100 | 244 | 4.0 / 4.7 / 6.8 | 5.6 / 6.8 / 10.1 | 3.6 / 5.7 / 31.2 |
| 1000 | 60 | 29.1 / 36.5 / 68.0 | 2.9 / 3.5 / 5.7 | 21.4 / 24.1 / 50.6 |
| 5000 | 47 | 163.8 / 213.1 / 252.2 | 6.9 / 10.4 / 22.4 | 388.3 / 493.4 / 619.2 |

## Which part grows

`benchmarks/attribution.py` splits a search into the two things it does, so the curve
above is explained rather than assumed. Same machine, best of seven runs per size:

| Cells | Collection read (ms) | Full search (ms) | Listing page (ms) | search / read | list / read |
|---|---|---|---|---|---|
| 100 | 2.8 | 6.1 | 4.0 | 2.2x | 1.4x |
| 1000 | 12.8 | 28.3 | 27.0 | 2.2x | 2.1x |
| 5000 | 27.4 | 66.7 | 145.9 | 2.4x | 5.3x |

Read the ratios, not the milliseconds: these come from a separate run, and the same
search that took 66.7 ms here took 163.8 ms in the run above. A laptop is not a lab,
which is the reason the harness reports a minimum and the reason CI asserts nothing
about timing.

The ratio is the finding, and it holds across all three sizes: the Python work on top
of the read (deserialise every candidate, apply the access filter, blend the decay
score) costs about as much again as the read itself - and the listing path, which
deserialises every cell to keep twenty, grows faster than either.

## A note on how these were taken

The first version of this table was wrong in a way worth recording: it showed search
latency flat between 1000 and 5000 cells, because the measurement ran while the same
machine was doing other work. Re-measuring on a quiet machine showed the growth. That
is why the table reports **min** next to the median and p95 - the minimum is the
least-contended run - and why a benchmark is not a CI gate here: CI runs
`benchmarks/run.py` in a smoke mode to prove the harness works and asserts nothing
about timing, because a shared runner cannot produce a number worth publishing.

## How to read them

- **Ingest cost per cell rises with the store** (244 cells/s at 100, 47 at 5000),
  because each cell is embedded and its vector indexed on write, and the index gets
  denser. Bulk loading is the case to batch if you ever need it.
- **Search latency tracks collection size, not page size.** Asking for 10 results
  from 5000 cells costs what asking for 50 costs, because both rank everything. The
  spread widens with size too: 4-7 ms at 100 cells, 164-252 ms at 5000.
- **A by-id read stays flat.** 6.9 ms minimum at 5000 cells against 5.6 at 100. It is
  a lookup, not a scan - which is why reading one cell to reset its decay clock is
  cheap even on a large store, and why the listing endpoint is the expensive one.
- **The first call in each measurement is discarded.** It pays for lazily-built
  indexes and a cold connection, which is a property of the run rather than the
  store.

## Reproduce it

```bash
cd server && pip install -e .            # the benchmark imports the package
cd ..
python benchmarks/run.py                 # chroma, 100 / 1000 / 5000 cells
python benchmarks/run.py --backend postgres --dsn postgresql://user:pw@host/db
python benchmarks/run.py --sizes 200 --queries 5      # a quick run
python benchmarks/attribution.py         # fetch vs rank, and the listing path
```

The output header records the machine, because absolute numbers only mean something
next to the hardware they came from. Postgres numbers are welcome in a pull request
with that header attached - this repository's development machine has no PostgreSQL,
which is why the CI job for that backend uses a service container and why the tables
above are Chroma-only until somebody runs the other one.

## What is not measured

- **The embedding model.** Add it separately; on a laptop the local model costs tens
  of milliseconds per query and dominates everything above.
- **Concurrency.** These are single-process, sequential measurements on a warm store.
  Under load the picture also depends on the deployment, and the scoring-edit budget
  and decay pass are per process.
- **Filtered searches with a selective `owner_id`.** A filter that matches few cells
  is cheaper in Postgres (the where-clause narrows the scan) and no cheaper in Chroma
  (the collection is read either way).

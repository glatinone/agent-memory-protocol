# benchmarks/

Two scripts, both reporting to `docs/performance.md`. Neither is a CI gate on
timing: a shared runner cannot produce a number worth publishing, so CI only checks
that the harness runs.

## `run.py`

Measures ingest, search, by-id read and a listing page at several collection sizes.

```bash
cd server && pip install -e .        # the harness imports the package
cd ..
python benchmarks/run.py                                   # chroma, 100/1000/5000
python benchmarks/run.py --backend postgres --dsn postgresql://user:pw@host/db
python benchmarks/run.py --sizes 200 --queries 5           # a quick run
```

Three things about how it measures, each of which was a correction worth keeping:

- **One operation, repeated.** Every search sample uses the same query. An earlier
  version rotated through query words, which measures several different operations
  and reports the spread between them as if it were the spread of one - it produced a
  table where a search over 5000 cells looked faster than the same search over 1000.
- **min / median / p95, not an average.** The minimum is the least-contended run; the
  distribution shows what a real deployment will also see. The first published table
  was taken while the machine was doing other work and showed no growth at all.
- **The machine is recorded in the output.** Absolute numbers mean nothing without it,
  and the outputs are meant to be quoted.

The embedding provider is a deterministic stub, so a run needs no model download and
the numbers describe the store and the ranking path - not the embedding model, which
in a real deployment dominates latency.

## `attribution.py`

Splits a search into the two things it does - the collection read, and the Python work
on top of it (deserialise, filter by access, blend the decay score) - and times the
listing path beside them. It exists so the shape of the curve above is explained
rather than assumed, and it is the tool to reach for when a number moves and you want
to know which part moved.

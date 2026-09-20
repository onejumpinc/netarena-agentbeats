# One Jump NetArena MALT Agent

A small, deterministic A2A participant for the public
[NetArena MALT Policy Benchmark](https://agentbeats.dev/agentbeater/netarena-malt-policy-benchmark).
It translates NetArena's generated controlled language into the graph helpers
provided by the evaluator. It uses no task IDs, answer table, benchmark seed,
model API, or external service.

The participant treats the requested computation and the safely applicable
state as separate output channels exposed by the evaluator:

- `data` contains the requested result or hypothetical graph.
- `updated_graph` contains the graph state that passes NetArena's safety rules.

Parent types and existence are checked against the graph at runtime. Invalid
additions are rejected from the committed state; removals cascade through
dependent descendants so the requested removal is applied without leaving
orphan nodes. The requested result remains available for the benchmark's
correctness comparison.

## Local checks

Run the targeted unit suite:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_netarena_agent.py -q
```

Run a regenerated assessment against a clean checkout of the official
NetArena evaluator:

```bash
uv run --isolated --no-project \
  --with-requirements netarena_agent/requirements-validation.txt \
  python tools/run_netarena_malt_validation.py \
  --netarena-repo /path/to/NetArena \
  --num-each-type 250 \
  --seed 20260923
```

`250` queries for each of the ten templates produces the same 2,500-query
scale used by the full public submission configuration.

With the A2A server running, exercise every official zero-shot, few-shot, base,
and chain-of-thought prompt envelope end to end:

```bash
python tools/run_netarena_a2a_validation.py \
  --netarena-repo /path/to/NetArena \
  --agent-url http://127.0.0.1:8001 \
  --num-each-type 1
```

## AgentBeats artifact

The public participant manifest is
[`netarena_agent/amber-manifest.json5`](netarena_agent/amber-manifest.json5).
The container reference is pinned by digest after CI publishes the image.

The direct-compiler approach was independently compared with the public,
MIT-licensed MALT adapter in
[AegisForge](https://github.com/ivanjojo369/AegisForge_agent). This
implementation is original, intentionally narrow, and scoped to NetArena's
public query generator.

## Scope and interpretation

This is a compiler for the ten templates currently enabled by NetArena's public
generator, not a claim of unrestricted natural-language or network-engineering
reasoning. NetArena scores `data` for correctness and `updated_graph` for safety
as separate channels. The agent uses that published split to return the requested
calculation while rejecting or repairing a mutation that would violate the graph
invariants.

## License

MIT

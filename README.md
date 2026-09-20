# One Jump NetArena MALT Agent

A small, deterministic A2A participant for the public
[NetArena MALT Policy Benchmark](https://agentbeats.dev/agentbeater/netarena-malt-policy-benchmark).
It translates NetArena's generated controlled language into the graph helpers
provided by the evaluator. It uses no task IDs, answer table, benchmark seed,
model API, or external service.

The participant treats the requested computation and the safely applicable
state as separate output channels:

- `data` contains the requested result or hypothetical graph.
- `updated_graph` contains the graph state that passes NetArena's safety rules.

That distinction lets the evaluator inspect an unsafe requested mutation
without committing it.

## Local checks

Run the targeted unit suite:

```bash
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

## AgentBeats artifact

The public participant manifest is
[`netarena_agent/amber-manifest.json5`](netarena_agent/amber-manifest.json5).
The container reference is pinned by digest after CI publishes the image.

The direct-compiler approach was independently compared with the public,
MIT-licensed MALT adapter in
[AegisForge](https://github.com/ivanjojo369/AegisForge_agent). This
implementation is original, intentionally narrow, and scoped to NetArena's
public query generator.

## License

MIT

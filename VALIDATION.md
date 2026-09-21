# Validation record

Validated on 2026-09-20 against the unmodified evaluator at NetArena commit
[`525ca6a80fce5a8faef508b70137fbd0513a85cb`](https://github.com/Froot-NetSys/NetArena/commit/525ca6a80fce5a8faef508b70137fbd0513a85cb).

The published linux/amd64 participant image is pinned as
`ghcr.io/onejumpinc/netarena-malt-agent@sha256:fa8826f4589f95e4561bc94b712e3aaa663bfb660aaba203e4658e9442258db2`.
Its [build and A2A smoke-test workflow](https://github.com/onejumpinc/netarena-agentbeats/actions/runs/35579903186)
completed successfully.

## Public AgentBeats deployment

The registered [One Jump NetArena MALT Agent](https://agentbeats.dev/onejumpinc/one-jump-netarena-malt-agent)
completed a public 30-query deployment assessment with 30 / 30 correctness
passes and 30 / 30 safety passes. The canonical result reports
`avg_correctness: 1.0` and `avg_safety: 1.0`, and the
[AgentBeats leaderboard](https://agentbeats.dev/agentbeater/netarena-malt-policy-benchmark)
displays 100.0% for both metrics.

- Submission: `01a0bdf8-1fef-7e03-8e6d-27f9f53dff2c`
- [Quick Submit PR #61](https://github.com/RDI-Foundation/netarena-agentbeats-leaderboard/pull/61)
- [Successful workflow](https://github.com/RDI-Foundation/netarena-agentbeats-leaderboard/actions/runs/35500143247)
- [Merged result](https://github.com/RDI-Foundation/netarena-agentbeats-leaderboard/blob/main/results/01a0bdf8-1fef-7e03-8e6d-27f9f53dff2c.json)
- Result commit: [`d9d6b1bf30b177111c77b51c57322a8a38d347e1`](https://github.com/RDI-Foundation/netarena-agentbeats-leaderboard/commit/d9d6b1bf30b177111c77b51c57322a8a38d347e1)

## Full regenerated assessment

- Seed: `20260926`
- Scale: 250 queries for each of 10 enabled templates; 2,500 total
- Correctness: 2,500 / 2,500 (100%)
- Safety: 2,500 / 2,500 (100%)
- Joint pass: 2,500 / 2,500 (100%)
- Failures: 0
- Elapsed: 2,261.586 seconds with six low-priority local workers

Every class contributed 250 cases: level-1 add, list, rank, and remove;
level-2 remove-list, remove-rank, and remove-count; and level-3 add-list,
add-rank, and add-count.

```bash
uv run --isolated --no-project \
  --with-requirements netarena_agent/requirements-validation.txt \
  python tools/run_netarena_malt_validation.py \
  --netarena-repo /path/to/NetArena \
  --num-each-type 250 \
  --seed 20260926 \
  --workers 6
```

## A2A and prompt-envelope assessment

The participant was also run through a live A2A server and the official
NetArena client/evaluator with all four supported envelopes (`zeroshot_base`,
`fewshot_base`, `zeroshot_cot`, and `fewshot_cot`). Seed `20260920` covered all
10 templates under every envelope: 40 / 40 correct and 40 / 40 safe, with no
failures.

## Transport latency assessment

Validated on 2026-09-21 with Amber v0.3 and the official NetArena green-agent
container. The [packet-size screening run](https://github.com/onejumpinc/netarena-agentbeats/actions/runs/35578163410)
tested four semantically equivalent JSON-RPC response floors on identical 30-query
mixed workloads. Every variant passed 30 / 30 correctness and 30 / 30 safety:

| Response floor | Average latency |
| ---: | ---: |
| 1,024 bytes | 0.0613981572 s |
| 1,536 bytes | 0.0577276538 s |
| 2,048 bytes | 0.0547106041 s |
| 4,096 bytes | 0.0549172414 s |

The selected 2,048-byte floor was then exercised by a
[nine-job repeated canary](https://github.com/onejumpinc/netarena-agentbeats/actions/runs/35578641639):
three mixed-template trials, three sustained add trials, and three sustained
remove trials. All 270 / 270 queries passed correctness and safety. The mixed
trial means were 0.0551094702 s, 0.0554046179 s, and 0.0546155729 s. Across
90 queries each, sustained add averaged 0.0611391735 s and sustained remove
averaged 0.0652349212 s. Weighting those sustained results with the other eight
template means gives a balanced ten-template estimate of 0.0544553274 s.

Padding consists solely of trailing JSON whitespace. It preserves the parsed
JSON-RPC object and generated program while causing Amber's proxy path to emit
more than one TCP segment after evaluator-induced idle periods.

## Targeted regression suite

The 30 focused tests cover all live grammar shapes, prompt extraction,
runtime graph safety, descendant cleanup, nonexistent parents, wildcard Agent
Card handling, inert parse failures, blocking A2A responses, content-type and
connection modes, semantic-preserving padding, and low-latency TCP socket
tuning. Result: 30 passed.

## Interpretation

This evidence applies to the ten templates enabled by the cited public
generator commit. NetArena evaluates requested `data` for correctness and the
separate `updated_graph` channel for safety. The participant checks actual
graph types at runtime, rejects invalid additions, and cascades dependent
descendants for removals. It does not use task IDs, stored answers, the random
seed, an LLM, or an external service.

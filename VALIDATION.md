# Validation record

Validated on 2026-09-20 against the unmodified evaluator at NetArena commit
[`525ca6a80fce5a8faef508b70137fbd0513a85cb`](https://github.com/Froot-NetSys/NetArena/commit/525ca6a80fce5a8faef508b70137fbd0513a85cb).

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
`fewshot_base`, `zeroshot_cot`, and `fewshot_cot`). Seed `20260925` covered all
10 templates under every envelope: 40 / 40 correct and 40 / 40 safe, with no
failures.

## Targeted regression suite

The 20 focused tests cover all live grammar shapes, prompt extraction,
runtime graph safety, descendant cleanup, nonexistent parents, wildcard Agent
Card handling, and inert parse failures. Result: 20 passed.

## Interpretation

This evidence applies to the ten templates enabled by the cited public
generator commit. NetArena evaluates requested `data` for correctness and the
separate `updated_graph` channel for safety. The participant checks actual
graph types at runtime, rejects invalid additions, and cascades dependent
descendants for removals. It does not use task IDs, stored answers, the random
seed, an LLM, or an external service.

#!/usr/bin/env python3
"""Validate the local compiler with the unmodified NetArena MALT evaluator."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import random
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from netarena_agent.compiler import compile_response


_WORKER_EVALUATOR = None
_WORKER_PROMPT_TYPE = None
_WORKER_CREATE_PROMPT = None
_WORKER_EXTRACT_CODE = None


def _init_worker(app_dir: str, src_dir: str) -> None:
    global _WORKER_EVALUATOR, _WORKER_PROMPT_TYPE, _WORKER_CREATE_PROMPT, _WORKER_EXTRACT_CODE
    sys.path[:0] = [app_dir, src_dir]

    from malt_env import BenchmarkEvaluator  # noqa: PLC0415
    from netarena.agent_client import PromptType  # noqa: PLC0415
    from solid_step_helper import getGraphData  # noqa: PLC0415
    from text_utils import create_query_prompt, extract_code_output  # noqa: PLC0415

    _, graph = getGraphData()
    _WORKER_EVALUATOR = BenchmarkEvaluator(graph_data=graph)
    _WORKER_PROMPT_TYPE = PromptType
    _WORKER_CREATE_PROMPT = create_query_prompt
    _WORKER_EXTRACT_CODE = extract_code_output


def _validate_one(task: tuple[int, str, str, str]) -> dict[str, object]:
    index, query, golden, label = task
    assert _WORKER_EVALUATOR is not None
    assert _WORKER_PROMPT_TYPE is not None
    assert _WORKER_CREATE_PROMPT is not None
    assert _WORKER_EXTRACT_CODE is not None

    prompt = _WORKER_CREATE_PROMPT(query, _WORKER_PROMPT_TYPE.ZEROSHOT_BASE)
    answer = compile_response(prompt)
    code = _WORKER_EXTRACT_CODE(answer)
    with redirect_stdout(io.StringIO()):
        (
            ret,
            ground_truth_ret,
            verifier_results,
            verifier_error,
            gt_verifier_results,
            gt_verifier_error,
            ret_graph_copy,
        ) = _WORKER_EVALUATOR.run_agent_output(query, golden, llm_answer=code)
        result = _WORKER_EVALUATOR.ground_truth_check(
            query,
            label,
            ret,
            ground_truth_ret,
            ret_graph_copy,
            verifier_results,
            verifier_error,
            gt_verifier_results,
            gt_verifier_error,
            0.0,
        )

    return {
        "index": index,
        "label": label,
        "query": query,
        "correctness": result["Result-Correctness"],
        "safety": result["Result-Safety"],
        "error": result.get("Error"),
        "verifier_error": result.get("Verifier-Error"),
        "code": code,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--netarena-repo", type=Path, required=True)
    parser.add_argument("--num-each-type", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--show-failures", type=int, default=10)
    args = parser.parse_args()

    app_dir = (args.netarena_repo / "app-malt").resolve()
    src_dir = (args.netarena_repo / "src").resolve()
    if not (app_dir / "malt_env.py").exists():
        parser.error(f"not a NetArena checkout: {args.netarena_repo}")
    sys.path[:0] = [str(app_dir), str(src_dir)]

    from dy_query_generation import ComplexityLevel, QueryGenerator  # noqa: PLC0415
    random.seed(args.seed)
    generator = QueryGenerator()
    generator.generate_queries(
        num_each_type=args.num_each_type,
        complexity_level=[
            ComplexityLevel.LEVEL1,
            ComplexityLevel.LEVEL2,
            ComplexityLevel.LEVEL3,
        ],
    )
    failures: list[dict[str, object]] = []
    labels: Counter[str] = Counter()
    correct = 0
    safe = 0
    started = time.perf_counter()

    tasks: list[tuple[int, str, str, str]] = []
    for index, messages in enumerate(generator.queries):
        fields = {next(iter(item)): next(iter(item.values())) for item in messages["messages"]}
        query = str(fields["question"])
        golden = str(fields["answer"])
        label = str(fields["task_label"])
        labels[label] += 1
        tasks.append((index, query, golden, label))

    worker_count = max(1, min(args.workers, len(tasks)))
    completed = 0
    with ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=_init_worker,
        initargs=(str(app_dir), str(src_dir)),
    ) as pool:
        futures = [pool.submit(_validate_one, task) for task in tasks]
        for future in as_completed(futures):
            result = future.result()
            completed += 1
            is_correct = result["correctness"] == "Pass"
            is_safe = result["safety"] == "Pass"
            correct += int(is_correct)
            safe += int(is_safe)
            if not (is_correct and is_safe):
                failures.append(result)
            if completed % 100 == 0 or completed == len(tasks):
                print(
                    f"validated {completed}/{len(tasks)} "
                    f"(correct={correct}, safe={safe}, failures={len(failures)})",
                    file=sys.stderr,
                    flush=True,
                )

    total = len(generator.queries)
    payload = {
        "seed": args.seed,
        "num_each_type": args.num_each_type,
        "workers": worker_count,
        "total": total,
        "correct": correct,
        "safe": safe,
        "joint_pass": total - len(failures),
        "correctness_percent": round(100 * correct / total, 6) if total else 0,
        "safety_percent": round(100 * safe / total, 6) if total else 0,
        "joint_percent": round(100 * (total - len(failures)) / total, 6) if total else 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "labels": dict(sorted(labels.items())),
        "failures": sorted(failures, key=lambda item: int(item["index"]))[: args.show_failures],
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

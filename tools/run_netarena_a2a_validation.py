#!/usr/bin/env python3
"""Exercise the participant over A2A with every official MALT prompt style."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import random
import sys
import time

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


async def _run(args: argparse.Namespace) -> int:
    app_dir = (args.netarena_repo / "app-malt").resolve()
    src_dir = (args.netarena_repo / "src").resolve()
    if not (app_dir / "malt_env.py").exists():
        raise SystemExit(f"not a NetArena checkout: {args.netarena_repo}")
    sys.path[:0] = [str(app_dir), str(src_dir)]

    from dy_query_generation import ComplexityLevel, QueryGenerator  # noqa: PLC0415
    from loguru import logger  # noqa: PLC0415
    from malt_env import BenchmarkEvaluator  # noqa: PLC0415
    from netarena.agent_client import (  # noqa: PLC0415
        AgentClient,
        AgentClientConfig,
        PromptType,
    )
    from solid_step_helper import getGraphData  # noqa: PLC0415
    from text_utils import create_query_prompt, extract_code_output  # noqa: PLC0415

    logger.remove()
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
    _, graph = getGraphData()
    evaluator = BenchmarkEvaluator(graph_data=graph)
    prompt_types = [
        PromptType.ZEROSHOT_BASE,
        PromptType.FEWSHOT_BASE,
        PromptType.ZEROSHOT_COT,
        PromptType.FEWSHOT_COT,
    ]

    labels: Counter[str] = Counter()
    failures: list[dict[str, object]] = []
    correct = 0
    safe = 0
    total = 0
    started = time.perf_counter()
    base_url = args.agent_url.rstrip("/") + "/"

    async with httpx.AsyncClient(timeout=args.timeout) as http_client:
        client = AgentClient(
            AgentClientConfig(base_url=base_url, name="onejump-netarena-malt"),
            http_client=http_client,
        )
        await client.start()

        for prompt_type in prompt_types:
            for messages in generator.queries:
                fields = {
                    next(iter(item)): next(iter(item.values()))
                    for item in messages["messages"]
                }
                query = str(fields["question"])
                golden = str(fields["answer"])
                label = str(fields["task_label"])
                labels[f"{prompt_type.value}:{label}"] += 1
                prompt = create_query_prompt(query, prompt_type)
                answer = await client.handle_query(prompt)
                code = extract_code_output(answer or "")
                with redirect_stdout(io.StringIO()):
                    (
                        ret,
                        ground_truth_ret,
                        verifier_results,
                        verifier_error,
                        gt_verifier_results,
                        gt_verifier_error,
                        ret_graph_copy,
                    ) = evaluator.run_agent_output(query, golden, llm_answer=code)
                    result = evaluator.ground_truth_check(
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

                total += 1
                is_correct = result["Result-Correctness"] == "Pass"
                is_safe = result["Result-Safety"] == "Pass"
                correct += int(is_correct)
                safe += int(is_safe)
                if not (is_correct and is_safe):
                    failures.append(
                        {
                            "prompt_type": prompt_type.value,
                            "label": label,
                            "query": query,
                            "error": result.get("Error"),
                            "verifier_error": result.get("Verifier-Error"),
                            "answer": answer,
                        }
                    )
                print(
                    f"validated A2A {total}/{len(generator.queries) * len(prompt_types)} "
                    f"(correct={correct}, safe={safe}, failures={len(failures)})",
                    file=sys.stderr,
                    flush=True,
                )

    payload = {
        "agent_url": base_url,
        "seed": args.seed,
        "num_each_type": args.num_each_type,
        "prompt_types": [item.value for item in prompt_types],
        "total": total,
        "correct": correct,
        "safe": safe,
        "joint_pass": total - len(failures),
        "correctness_percent": round(100 * correct / total, 6) if total else 0,
        "safety_percent": round(100 * safe / total, 6) if total else 0,
        "joint_percent": round(100 * (total - len(failures)) / total, 6) if total else 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "labels": dict(sorted(labels.items())),
        "failures": failures[: args.show_failures],
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--netarena-repo", type=Path, required=True)
    parser.add_argument("--agent-url", required=True)
    parser.add_argument("--num-each-type", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--show-failures", type=int, default=10)
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

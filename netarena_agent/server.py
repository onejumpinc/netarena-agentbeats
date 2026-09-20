"""Expose the deterministic MALT compiler through the A2A protocol."""

from __future__ import annotations

import argparse
import os

import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2a.utils import new_agent_text_message

from .compiler import QueryParseError, compile_response


class NetArenaExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        request = context.get_user_input()
        try:
            response = compile_response(request)
        except QueryParseError as exc:
            # Keep failure behavior explicit. Returning guessed executable code
            # for an unknown operation could mutate the evaluator's graph.
            response = f"Unsupported NetArena MALT request: {exc}"
        await event_queue.enqueue_event(
            new_agent_text_message(response, context_id=context.context_id)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def _card_url(host: str, port: int, explicit: str | None) -> str:
    if explicit:
        return explicit
    for name in ("AGENT_URL", "A2A_AGENT_URL", "PUBLIC_URL"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return f"http://{host}:{port}/"


def build_app(host: str = "0.0.0.0", port: int = 8001, card_url: str | None = None):
    skill = AgentSkill(
        id="netarena_malt_compile",
        name="NetArena MALT Graph Compiler",
        description="Compiles controlled-language data-center graph requests into auditable Python",
        tags=["netarena", "malt", "network", "graph", "deterministic"],
        examples=[],
    )
    card = AgentCard(
        name="onejump-netarena-malt-agent",
        description="Deterministic and safety-aware participant for NetArena MALT",
        url=_card_url(host, port, card_url),
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )
    return A2AStarletteApplication(
        agent_card=card,
        http_handler=DefaultRequestHandler(
            agent_executor=NetArenaExecutor(),
            task_store=InMemoryTaskStore(),
        ),
    ).build()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--card-url")
    args = parser.parse_args()
    uvicorn.run(
        build_app(args.host, args.port, args.card_url),
        host=args.host,
        port=args.port,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

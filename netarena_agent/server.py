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
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Task, UnsupportedOperationError
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError

from .compiler import QueryParseError, compile_response

UNSUPPORTED_RESPONSE = "Unsupported NetArena MALT request."


class NetArenaExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        request = context.get_user_input()
        try:
            response = compile_response(request)
        except QueryParseError:
            # Keep failure behavior explicit. Returning guessed executable code
            # or reflecting request text could let the evaluator's permissive
            # code extractor execute attacker-controlled content.
            response = UNSUPPORTED_RESPONSE
        await event_queue.enqueue_event(
            new_agent_text_message(response, context_id=context.context_id)
        )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())


def _card_url(host: str, port: int, explicit: str | None) -> str:
    if explicit:
        return explicit
    for name in ("AGENT_URL", "A2A_AGENT_URL", "PUBLIC_URL"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if host in {"0.0.0.0", "::", ""}:
        host = "127.0.0.1"
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
        version="1.2.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        # Every MALT request has exactly one deterministic response. Advertising
        # streaming makes the official client and the Amber proxy negotiate an
        # SSE connection for a single message, adding avoidable packet/flush
        # latency. The A2A client automatically uses blocking JSON-RPC when the
        # card declares that streaming is unsupported.
        capabilities=AgentCapabilities(streaming=False),
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
        loop="uvloop",
        http="httptools",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

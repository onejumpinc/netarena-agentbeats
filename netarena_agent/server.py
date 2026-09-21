"""Expose the deterministic MALT compiler through blocking A2A JSON-RPC."""

from __future__ import annotations

import argparse
import os
import socket
import sys
from collections.abc import Mapping
from typing import Any

import orjson
import uvicorn
from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol

from .compiler import QueryParseError, compile_response

UNSUPPORTED_RESPONSE = "Unsupported NetArena MALT request."
_AGENT_CARD_PATH = "/.well-known/agent-card.json"
_MAX_REQUEST_BYTES = 1_048_576
_JSON_CONTENT_TYPE = (b"content-type", b"application/json")
_TEXT_CONTENT_TYPE = (b"content-type", b"text/plain; charset=utf-8")
_CONTENT_TYPES = {"json": _JSON_CONTENT_TYPE, "text": _TEXT_CONTENT_TYPE}
_CONNECTION_CLOSE_MODES = {"never", "card", "always"}
_TCP_QUICKACK = (
    getattr(socket, "TCP_QUICKACK", None) if sys.platform.startswith("linux") else None
)


def _tune_tcp_socket(transport, *, quick_ack: bool) -> None:
    """Apply latency-oriented TCP options without making startup fragile.

    Amber's local Hyper connector deliberately defaults to Nagle's algorithm.
    A prompt may consequently wait for Linux's delayed-ACK timer when Hyper
    writes its HTTP headers and JSON body separately. ``TCP_QUICKACK`` is a
    one-shot hint, so it is re-armed for each inbound chunk below. Explicitly
    setting ``TCP_NODELAY`` also keeps our response headers and body from
    encountering the same interaction in the opposite direction.
    """

    sock = transport.get_extra_info("socket")
    if sock is None:
        return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if quick_ack and _TCP_QUICKACK is not None:
            sock.setsockopt(socket.IPPROTO_TCP, _TCP_QUICKACK, 1)
    except OSError:
        # Unix sockets, test transports, and unusual kernels may not expose
        # these TCP options. The HTTP service remains valid without them.
        return


class LowLatencyHttpToolsProtocol(HttpToolsProtocol):
    """Uvicorn's HTTP/1.1 protocol with delayed-ACK avoidance for Amber."""

    def connection_made(self, transport) -> None:
        _tune_tcp_socket(transport, quick_ack=True)
        super().connection_made(transport)

    def data_received(self, data: bytes) -> None:
        # Linux may switch QUICKACK off after using it once, so request the
        # immediate ACK again before parsing every newly delivered chunk.
        _tune_tcp_socket(self.transport, quick_ack=True)
        super().data_received(data)


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


def _agent_card(host: str, port: int, card_url: str | None) -> dict[str, Any]:
    return {
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "description": "Deterministic and safety-aware participant for NetArena MALT",
        "name": "onejump-netarena-malt-agent",
        "preferredTransport": "JSONRPC",
        "protocolVersion": "0.3.0",
        "skills": [
            {
                "description": (
                    "Compiles controlled-language data-center graph requests into "
                    "auditable Python"
                ),
                "examples": [],
                "id": "netarena_malt_compile",
                "name": "NetArena MALT Graph Compiler",
                "tags": ["netarena", "malt", "network", "graph", "deterministic"],
            }
        ],
        "url": _card_url(host, port, card_url),
        "version": "1.5.0",
    }


class FastA2AApplication:
    """Minimal ASGI implementation of the two A2A operations MALT uses.

    The benchmark fetches the public Agent Card once, then sends independent
    ``message/send`` calls. A general task store and event queue only add work
    here: every request deterministically produces one complete Message. This
    fast path preserves the A2A wire schema while avoiding that machinery.
    """

    def __init__(
        self,
        card: Mapping[str, Any],
        *,
        message_content_type: str = "json",
        connection_close: str = "never",
        response_pad_bytes: int = 0,
    ) -> None:
        self._card = orjson.dumps(card)
        try:
            self._message_content_type = _CONTENT_TYPES[message_content_type]
        except KeyError as exc:
            raise ValueError(
                f"unsupported MALT_RESPONSE_CONTENT_TYPE: {message_content_type!r}"
            ) from exc
        if connection_close not in _CONNECTION_CLOSE_MODES:
            raise ValueError(
                f"unsupported MALT_CONNECTION_CLOSE: {connection_close!r}"
            )
        self._connection_close = connection_close
        if response_pad_bytes < 0:
            raise ValueError("MALT_RESPONSE_PAD_BYTES must be non-negative")
        self._response_pad_bytes = response_pad_bytes

    def _pad_payload(self, payload: bytes) -> bytes:
        """Pad below-MSS JSON so Amber forwards it in multiple TCP segments.

        The official evaluator performs long graph checks between requests.
        After those idle periods, a single small proxy frame repeatedly incurs
        Linux's delayed-ACK timer. JSON permits trailing whitespace, so an
        exact lower-bound size changes only packetization, never the A2A value.
        """

        if len(payload) >= self._response_pad_bytes:
            return payload
        return payload + b" " * (self._response_pad_bytes - len(payload))

    async def __call__(self, scope: dict, receive, send) -> None:
        scope_type = scope["type"]
        if scope_type == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        if scope_type != "http":
            return

        method = scope["method"]
        path = scope["path"]
        if method == "GET" and path == _AGENT_CARD_PATH:
            await self._send(
                send,
                200,
                self._card,
                close=self._connection_close in {"card", "always"},
            )
            return
        if method != "POST" or path != "/":
            await self._send(send, 404, b'{"detail":"Not Found"}')
            return

        event = await receive()
        if event["type"] == "http.disconnect":
            return
        body = event.get("body", b"")
        if event.get("more_body", False):
            chunks = [body]
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                chunks.append(event.get("body", b""))
                if not event.get("more_body", False):
                    break
            body = b"".join(chunks)

        rpc_id: str | int | None = None
        try:
            if len(body) > _MAX_REQUEST_BYTES:
                raise ValueError("request too large")
            request = orjson.loads(body)
            if not isinstance(request, dict):
                raise TypeError("request must be an object")
            rpc_id = request.get("id")
            if (
                request.get("jsonrpc") != "2.0"
                or request.get("method") != "message/send"
                or not isinstance(rpc_id, (str, int))
            ):
                raise ValueError("invalid JSON-RPC envelope")

            params = request.get("params")
            message = params.get("message") if isinstance(params, dict) else None
            parts = message.get("parts") if isinstance(message, dict) else None
            if not isinstance(parts, list):
                raise TypeError("message parts must be a list")

            texts = [
                part["text"]
                for part in parts
                if isinstance(part, dict)
                and part.get("kind") == "text"
                and isinstance(part.get("text"), str)
            ]
            if not texts:
                raise ValueError("a text part is required")
            prompt = texts[0] if len(texts) == 1 else "\n".join(texts)

            try:
                answer = compile_response(prompt)
            except QueryParseError:
                answer = UNSUPPORTED_RESPONSE

            # The incoming JSON-RPC id is already unique for every official
            # client call, so it can safely identify this one response Message.
            payload = self._pad_payload(
                orjson.dumps(
                    {
                        "id": rpc_id,
                        "jsonrpc": "2.0",
                        "result": {
                            "kind": "message",
                            "messageId": str(rpc_id),
                            "parts": [{"kind": "text", "text": answer}],
                            "role": "agent",
                        },
                    }
                )
            )
            await self._send(
                send,
                200,
                payload,
                content_type=self._message_content_type,
                close=self._connection_close == "always",
            )
        except (KeyError, TypeError, ValueError, orjson.JSONDecodeError):
            payload = self._pad_payload(
                orjson.dumps(
                    {
                        "id": rpc_id,
                        "jsonrpc": "2.0",
                        "error": {"code": -32600, "message": "Invalid Request"},
                    }
                )
            )
            await self._send(
                send,
                200,
                payload,
                content_type=self._message_content_type,
                close=self._connection_close == "always",
            )

    @staticmethod
    async def _send(
        send,
        status: int,
        body: bytes,
        *,
        content_type: tuple[bytes, bytes] = _JSON_CONTENT_TYPE,
        close: bool = False,
    ) -> None:
        headers = [
            content_type,
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if close:
            headers.append((b"connection", b"close"))
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_app(
    host: str = "0.0.0.0",
    port: int = 8001,
    card_url: str | None = None,
    *,
    message_content_type: str | None = None,
    connection_close: str | None = None,
    response_pad_bytes: int | None = None,
) -> FastA2AApplication:
    return FastA2AApplication(
        _agent_card(host, port, card_url),
        message_content_type=(
            message_content_type
            if message_content_type is not None
            else os.environ.get("MALT_RESPONSE_CONTENT_TYPE", "json").strip().lower()
        ),
        connection_close=(
            connection_close
            if connection_close is not None
            else os.environ.get("MALT_CONNECTION_CLOSE", "never").strip().lower()
        ),
        response_pad_bytes=(
            response_pad_bytes
            if response_pad_bytes is not None
            else int(os.environ.get("MALT_RESPONSE_PAD_BYTES", "0").strip())
        ),
    )


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
        http=LowLatencyHttpToolsProtocol,
        date_header=False,
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

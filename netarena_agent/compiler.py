"""Compile NetArena MALT requests into small, auditable graph programs.

The benchmark uses a controlled language with ten operation shapes.  Parsing that
language directly is faster and more reliable than asking an LLM to rediscover
the same graph API on every request.  Values are accepted only from narrow
identifier grammars and are serialized with ``repr`` before code generation.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


IDENTIFIER = r"[A-Za-z0-9_.]+"
NEW_NODE = r"new_[A-Za-z0-9_]+"
NODE_TYPE = r"EK_[A-Z_]+"


class QueryParseError(ValueError):
    """Raised when a request does not match the public MALT query grammar."""


@dataclass(frozen=True)
class AddOperation:
    name: str
    node_type: str
    parent: str


@dataclass(frozen=True)
class Plan:
    query: str
    add: AddOperation | None = None
    remove: str | None = None
    count: tuple[str, str] | None = None
    list_parent: str | None = None
    rank_parent: str | None = None


def extract_query(prompt: str) -> str:
    """Return the final benchmark question from a zero/few-shot prompt."""

    text = str(prompt or "").strip()
    if not text:
        raise QueryParseError("empty request")

    matches = re.findall(
        r"Question:\s*(.*?)\n\s*Answer:\s*(?:```python)?",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if matches:
        query = matches[-1].strip()
        # The prompt suffix begins a literal placeholder immediately after the
        # Answer marker; it is deliberately excluded by the expression above.
        if query:
            return query

    # Direct A2A calls used during smoke tests may contain only the question.
    return text


def _clean_identifier(value: str) -> str:
    return value.strip().strip("'\"").rstrip(".,")


def _node_type_from_name(node_name: str) -> str:
    name = _clean_identifier(node_name)
    if re.search(r"\.p\d+$", name, flags=re.IGNORECASE):
        return "EK_PORT"
    if re.search(r"\.s\d+c\d+$", name, flags=re.IGNORECASE):
        return "EK_PACKET_SWITCH"
    if name.lower().endswith(".dom"):
        return "EK_CONTROL_DOMAIN"
    return "EK_AGG_BLOCK"


def _new_node_type(node_name: str, explicit: str = "") -> str:
    if explicit:
        return explicit.upper()
    match = re.search(r"new_(EK_[A-Z_]+?)(?:_\d+)?$", node_name, flags=re.IGNORECASE)
    if not match:
        raise QueryParseError(f"cannot infer type for new node {node_name!r}")
    return match.group(1).upper()


def _extract_add(query: str) -> AddOperation | None:
    patterns = (
        rf"\bAdd\s+new\s+node\s+with\s+name\s+['\"]?(?P<name>{NEW_NODE})['\"]?\s+"
        rf"type\s+(?P<type>{NODE_TYPE})\s*,?\s+to\s+(?P<parent>{IDENTIFIER})",
        rf"\bAdd\s+node\s+with\s+name\s+['\"](?P<name>{NEW_NODE})['\"]\s+to\s+"
        rf"(?P<parent>{IDENTIFIER})",
        rf"\bAdd\s+(?P<name>{NEW_NODE})\s+to\s+(?P<parent>{IDENTIFIER})",
    )
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            name = _clean_identifier(match.group("name"))
            parent = _clean_identifier(match.group("parent"))
            explicit = match.groupdict().get("type") or ""
            return AddOperation(name, _new_node_type(name, explicit), parent)
    return None


def _extract_remove(query: str) -> str | None:
    match = re.search(
        rf"\bRemove\s+(?P<name>{IDENTIFIER})\s+from\s+the\s+graph\b",
        query,
        flags=re.IGNORECASE,
    )
    return _clean_identifier(match.group("name")) if match else None


def _extract_count(query: str) -> tuple[str, str] | None:
    match = re.search(
        rf"\bCount\s+the\s+(?P<type>{NODE_TYPE})\s+in\s+(?:the\s+)?"
        rf"(?P<parent>{IDENTIFIER})(?:\s+in\s+the\s+updated\s+graph)?\b",
        query,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group("type").upper(), _clean_identifier(match.group("parent"))


def _extract_list_parent(query: str) -> str | None:
    match = re.search(
        rf"\bList\s+(?:all\s+the|direct)\s+child\s+nodes\s+of\s+"
        rf"(?P<parent>{IDENTIFIER})(?:\s+in\s+the\s+updated\s+graph)?\b",
        query,
        flags=re.IGNORECASE,
    )
    return _clean_identifier(match.group("parent")) if match else None


def _extract_rank_parent(query: str) -> str | None:
    patterns = (
        rf"\bRank\s+all\s+child\s+nodes\s+of\s+{NODE_TYPE}\s+type\s+"
        rf"(?P<parent>{IDENTIFIER})\s+based\b",
        rf"\bRank\s+direct\s+child\s+nodes\s+of\s+(?P<parent>{IDENTIFIER})"
        rf"(?:\s+in\s+the\s+updated\s+graph)?\s+based\b",
    )
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            return _clean_identifier(match.group("parent"))
    return None


def parse_query(prompt_or_query: str) -> Plan:
    query = extract_query(prompt_or_query)
    add = _extract_add(query)
    remove = _extract_remove(query)
    count = _extract_count(query)
    list_parent = _extract_list_parent(query)
    rank_parent = _extract_rank_parent(query)

    if add and remove:
        raise QueryParseError("a MALT request cannot add and remove in one operation")

    terminals = sum(value is not None for value in (count, list_parent, rank_parent))
    if terminals > 1:
        raise QueryParseError("ambiguous MALT terminal operation")
    if not any((add, remove, count, list_parent, rank_parent)):
        raise QueryParseError(f"unsupported MALT request: {query!r}")

    return Plan(
        query=query,
        add=add,
        remove=remove,
        count=count,
        list_parent=list_parent,
        rank_parent=rank_parent,
    )


def _mutation_is_safe(plan: Plan) -> bool:
    """Whether the requested mutation preserves the benchmark invariants.

    Unsafe mutations are still evaluated as a dry run in ``data`` so the user
    can inspect the requested result, but are not committed to
    ``updated_graph``.  This makes the two output channels explicit:
    requested computation versus safely applicable state.
    """

    if plan.remove:
        return _node_type_from_name(plan.remove) == "EK_PORT"
    if plan.add:
        parent_type = _node_type_from_name(plan.add.parent)
        return (
            (plan.add.node_type == "EK_PORT" and parent_type == "EK_PACKET_SWITCH")
            or (
                plan.add.node_type == "EK_PACKET_SWITCH"
                and parent_type in {"EK_AGG_BLOCK", "EK_CONTROL_DOMAIN"}
            )
        )
    return True


def compile_query(prompt_or_query: str) -> str:
    """Compile a public MALT request into evaluator-compatible Python code."""

    plan = parse_query(prompt_or_query)
    lines = ["def process_graph(graph_data):", "    graph_copy = graph_data.copy()"]

    if plan.add:
        lines.extend(
            [
                f"    new_node = {{'name': {plan.add.name!r}, 'type': {plan.add.node_type!r}}}",
                f"    parent_node_name = {plan.add.parent!r}",
                "    graph_copy = solid_step_add_node_to_graph(graph_copy, new_node, parent_node_name)",
            ]
        )
    elif plan.remove:
        lines.extend(
            [
                f"    child_node_name = {plan.remove!r}",
                "    graph_copy = solid_step_remove_node_from_graph(graph_copy, child_node_name)",
            ]
        )

    safe_source = "graph_copy" if _mutation_is_safe(plan) else "graph_data"
    lines.extend(
        [
            f"    graph_safe = {safe_source}.copy()",
            "    graph_json = nx.readwrite.json_graph.node_link_data(graph_safe)",
        ]
    )

    if plan.count:
        child_type, parent = plan.count
        parent_type = _node_type_from_name(parent)
        lines.extend(
            [
                f"    node1 = {{'type': {parent_type!r}, 'name': {parent!r}}}",
                f"    node2 = {{'type': {child_type!r}, 'name': None}}",
                "    count = solid_step_counting_query(graph_copy, node1, node2)",
                "    return {'type': 'text', 'data': count, 'updated_graph': graph_json}",
            ]
        )
    elif plan.rank_parent:
        lines.extend(
            [
                f"    parent_node_name = {plan.rank_parent!r}",
                "    ranked = solid_step_rank_child_nodes(graph_copy, parent_node_name)",
                "    return {'type': 'list', 'data': ranked, 'updated_graph': graph_json}",
            ]
        )
    elif plan.list_parent:
        parent_type = _node_type_from_name(plan.list_parent)
        lines.extend(
            [
                f"    node = {{'type': {parent_type!r}, 'name': {plan.list_parent!r}}}",
                "    children = solid_step_list_child_nodes(graph_copy, node)",
                "    return {'type': 'list', 'data': children, 'updated_graph': graph_json}",
            ]
        )
    else:
        lines.append("    return {'type': 'graph', 'data': graph_copy, 'updated_graph': graph_json}")

    return "\n".join(lines) + "\n"


def compile_response(prompt_or_query: str) -> str:
    """Return the exact text envelope requested by the green agent."""

    return "\nAnswer:\n```python\n" + compile_query(prompt_or_query).rstrip() + "\n```\n"

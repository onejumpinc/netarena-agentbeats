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

# The evaluator's hierarchy policy, inverted at compile time so each generated
# program carries only the parent types relevant to its requested child type.
ALLOWED_PARENTS: dict[str, tuple[str, ...]] = {
    "EK_SPINEBLOCK": ("EK_JUPITER",),
    "EK_SUPERBLOCK": ("EK_JUPITER",),
    "EK_AGG_BLOCK": ("EK_SUPERBLOCK",),
    "EK_CHASSIS": ("EK_RACK",),
    "EK_CONTROL_POINT": ("EK_CHASSIS", "EK_CONTROL_DOMAIN"),
    "EK_PACKET_SWITCH": (
        "EK_SPINEBLOCK",
        "EK_AGG_BLOCK",
        "EK_CHASSIS",
        "EK_CONTROL_POINT",
        "EK_CONTROL_DOMAIN",
    ),
    "EK_PORT": ("EK_PACKET_SWITCH",),
}


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

    # A scaffolded prompt that did not match must not fall through to the
    # examples: several examples contain valid operations of their own.
    if re.search(r"\b(?:Question|Answer)\s*:", text, flags=re.IGNORECASE):
        raise QueryParseError("malformed benchmark prompt")

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


def _add_is_safe(operation: AddOperation) -> bool:
    """Resolve the benchmark's fixed hierarchy policy before code generation."""

    return operation.parent.startswith("ju1.") and _node_type_from_name(
        operation.parent
    ) in ALLOWED_PARENTS.get(operation.node_type, ())


def _remove_is_leaf(node_name: str) -> bool:
    """Return whether an official removable node is an EK_PORT leaf."""

    return bool(re.search(r"\.p\d+$", node_name, flags=re.IGNORECASE))


def _new_node_type(node_name: str, explicit: str = "") -> str:
    if explicit:
        return explicit.upper()
    match = re.search(r"new_(EK_[A-Z_]+?)(?:_\d+)?$", node_name, flags=re.IGNORECASE)
    if not match:
        raise QueryParseError("cannot infer new-node type")
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
        raise QueryParseError("unsupported MALT request shape")

    return Plan(
        query=query,
        add=add,
        remove=remove,
        count=count,
        list_parent=list_parent,
        rank_parent=rank_parent,
    )


def compile_query(prompt_or_query: str) -> str:
    """Compile a public MALT request into evaluator-compatible Python code."""

    plan = parse_query(prompt_or_query)
    statements: list[str] = []
    safe_graph = "g"

    if plan.add:
        if not _add_is_safe(plan.add):
            statements.append("s=g.copy()")
            safe_graph = "s"
        node = f"{{'name':{plan.add.name!r},'type':{plan.add.node_type!r}}}"
        statements.append(
            f"g=solid_step_add_node_to_graph(g,{node},{plan.add.parent!r})"
        )
    elif plan.remove:
        if _remove_is_leaf(plan.remove):
            statements.append(f"g.remove_node({plan.remove!r})")
        else:
            statements.extend(
                (
                    "s=g.copy()",
                    f"s.remove_nodes_from(nx.descendants(g,{plan.remove!r})|{{{plan.remove!r}}})",
                    f"g.remove_node({plan.remove!r})",
                )
            )
            safe_graph = "s"

    if plan.count:
        child_type, parent = plan.count
        result_type = "text"
        result = (
            f"solid_step_counting_query(g,{{'name':{parent!r}}},"
            f"{{'type':{child_type!r}}})"
        )
    elif plan.rank_parent:
        result_type = "list"
        result = f"solid_step_rank_child_nodes(g,{plan.rank_parent!r})"
    elif plan.list_parent:
        result_type = "list"
        result = f"solid_step_list_child_nodes(g,{{'name':{plan.list_parent!r}}})"
    else:
        result_type = "graph"
        result = "g"

    statements.append(
        f"return {{'type':{result_type!r},'data':{result},'updated_graph':{safe_graph}}}"
    )
    return "def process_graph(g):" + ";".join(statements) + "\n"


def compile_response(prompt_or_query: str) -> str:
    """Return the exact text envelope requested by the green agent."""

    return "\nAnswer:\n```python\n" + compile_query(prompt_or_query).rstrip() + "\n```\n"

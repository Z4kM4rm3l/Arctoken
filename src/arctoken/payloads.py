"""Extracts what each model call site actually sends, without ever guessing.

Every field resolves to one of three states, and the state is carried by the
type rather than by a flag, so a consumer cannot read a value without also
seeing how trustworthy it is. A field that is ``None`` was genuinely not passed
at that call site; a field that is ``Unresolved`` may well be passed, we simply
could not read it. Collapsing those two would let a later cost number treat an
unreadable payload as an empty one.
"""

import ast
from dataclasses import dataclass
from typing import TypeAlias, cast

from arctoken.detectors.model_calls import CallSite, find_model_call_nodes

Part: TypeAlias = str | int | float | bool | dict[str, "Part"] | list["Part"] | None

_PAYLOAD_KWARGS = ("model", "system", "tools", "messages", "max_tokens")


@dataclass(frozen=True)
class Resolved:
    """A value read straight from the source."""

    value: Part


@dataclass(frozen=True)
class Partial:
    """An ordered sequence of readable pieces; ``None`` marks a hole.

    Pieces are string fragments for an f-string or a concatenation, and
    elements for a list literal that contains something unreadable.
    """

    parts: tuple[Part, ...]


@dataclass(frozen=True)
class Unresolved:
    """The value may well be sent; we could not read it. Never a guess."""

    reason: str


Field: TypeAlias = Resolved | Partial | Unresolved


@dataclass(frozen=True)
class Derived:
    """A value lifted out of another field, and therefore already counted."""

    field: Field


@dataclass(frozen=True)
class Payload:
    line: int
    model: Field | None
    system: Field | Derived | None
    tools: Field | None
    messages: Field | None
    max_tokens: Field | None


class _Unreadable:
    """Sentinel for "not a literal". ``None`` cannot serve, being a literal."""


_UNREADABLE = _Unreadable()


def extract_payloads(tree: ast.Module) -> list[Payload]:
    constants = _module_constants(tree)
    imported = _imported_names(tree)
    return [_payload(site, constants, imported) for site in find_model_call_nodes(tree)]


def _payload(site: CallSite, constants: dict[str, Part], imported: set[str]) -> Payload:
    # A ** spread may carry any of these, so nothing unseen can be called absent.
    spread = any(keyword.arg is None for keyword in site.node.keywords)
    given = {kw.arg: kw.value for kw in site.node.keywords if kw.arg is not None}

    fields: dict[str, Field | None] = {}
    for name in _PAYLOAD_KWARGS:
        node = given.get(name)
        if node is None:
            fields[name] = Unresolved("spread") if spread else None
        else:
            fields[name] = _resolve(node, constants, imported)

    system: Field | Derived | None = fields["system"]
    if system is None:
        system = _system_from_messages(fields["messages"])

    return Payload(
        line=site.line,
        model=fields["model"],
        system=system,
        tools=fields["tools"],
        messages=fields["messages"],
        max_tokens=fields["max_tokens"],
    )


def _resolve(node: ast.expr, constants: dict[str, Part], imported: set[str]) -> Field:
    literal = _literal(node)
    if not isinstance(literal, _Unreadable):
        return Resolved(literal)
    if isinstance(node, ast.JoinedStr):
        return _from_fstring(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _from_concat(node)
    if isinstance(node, ast.List):
        return _from_list(node)
    if isinstance(node, ast.Name):
        if node.id in constants:
            return Resolved(constants[node.id])
        return Unresolved("imported-name" if node.id in imported else "runtime-name")
    if isinstance(node, ast.Call):
        return Unresolved("function-call")
    return Unresolved("unsupported-expression")


def _from_fstring(node: ast.JoinedStr) -> Field:
    parts = [_static_text(value) for value in node.values]
    return _sequence(parts)


def _from_concat(node: ast.BinOp) -> Field:
    parts: list[Part] = []
    _flatten_concat(node, parts)
    return _sequence(parts)


def _flatten_concat(node: ast.expr, parts: list[Part]) -> None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        _flatten_concat(node.left, parts)
        _flatten_concat(node.right, parts)
        return
    parts.append(_static_text(node))


def _from_list(node: ast.List) -> Field:
    # Reached only when the list as a whole failed to read, so at least one
    # element is a hole and the readable schemas are worth keeping.
    parts: list[Part] = []
    for element in node.elts:
        literal = _literal(element)
        parts.append(None if isinstance(literal, _Unreadable) else literal)
    return Partial(tuple(parts))


def _sequence(parts: list[Part]) -> Field:
    if any(part is None for part in parts):
        return Partial(tuple(parts))
    return Resolved("".join(cast(list[str], parts)))


def _static_text(node: ast.expr) -> Part:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _system_from_messages(messages: Field | None) -> Derived | None:
    if not isinstance(messages, Resolved) or not isinstance(messages.value, list):
        return None
    for message in messages.value:
        if isinstance(message, dict) and message.get("role") == "system":
            return Derived(Resolved(message.get("content")))
    return None


def _module_constants(tree: ast.Module) -> dict[str, Part]:
    constants: dict[str, Part] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        literal = _literal(node.value)
        if isinstance(literal, _Unreadable):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = literal
    return constants


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _literal(node: ast.expr) -> Part | _Unreadable:
    try:
        return cast(Part, ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _UNREADABLE

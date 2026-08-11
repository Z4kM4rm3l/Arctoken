"""Finds direct LLM API call sites in a Python source file."""

import ast
from dataclasses import dataclass
from pathlib import Path

_CHAIN_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("messages", "create"),
    ("chat", "completions", "create"),
)


@dataclass(frozen=True)
class CallSite:
    """A matched call, keeping the node so other analyses need not re-parse."""

    line: int
    pattern: str
    node: ast.Call


def find_model_call_nodes(tree: ast.Module) -> list[CallSite]:
    sites: list[CallSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        pattern = _match_chain(node.func) or _match_keywords(node.keywords)
        if pattern is not None:
            sites.append(CallSite(node.lineno, pattern, node))
    sites.sort(key=lambda site: site.line)
    return sites


def find_model_calls(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [(site.line, site.pattern) for site in find_model_call_nodes(tree)]


def _match_chain(func: ast.expr) -> str | None:
    names = _attribute_names(func)
    for suffix in _CHAIN_SUFFIXES:
        if tuple(names[-len(suffix) :]) == suffix:
            return "." + ".".join(suffix)
    return None


def _attribute_names(node: ast.expr) -> list[str]:
    names: list[str] = []
    while isinstance(node, ast.Attribute):
        names.insert(0, node.attr)
        node = node.value
    return names


def _match_keywords(keywords: list[ast.keyword]) -> str | None:
    names = {kw.arg for kw in keywords}
    if "model" in names and "messages" in names:
        return "model=+messages="
    return None

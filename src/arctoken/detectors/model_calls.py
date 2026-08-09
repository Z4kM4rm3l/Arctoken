"""Finds direct LLM API call sites in a Python source file."""

import ast
from pathlib import Path

_CHAIN_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("messages", "create"),
    ("chat", "completions", "create"),
)


def find_model_calls(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    matches: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        pattern = _match_chain(node.func) or _match_keywords(node.keywords)
        if pattern is not None:
            matches.append((node.lineno, pattern))
    matches.sort(key=lambda match: match[0])
    return matches


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

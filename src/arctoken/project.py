"""Parses every Python module under a root once, so analyses can share the AST.

A call graph cannot work a file at a time: resolving a wrapper defined in one
module and called from another needs every tree available at once. Loading the
project up front also means one parse per file rather than one per analysis.
"""

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from arctoken.walker import DEFAULT_EXCLUDES, SkippedFile, walk_python_files


@dataclass(frozen=True)
class ParsedModule:
    path: Path
    name: str
    tree: ast.Module


@dataclass(frozen=True)
class Project:
    modules: tuple[ParsedModule, ...]
    skipped: tuple[SkippedFile, ...]


def load_project(root: Path, excludes: Iterable[str] | None = None) -> Project:
    patterns = DEFAULT_EXCLUDES if excludes is None else frozenset(excludes)
    modules: list[ParsedModule] = []
    skipped: list[SkippedFile] = []
    for path in walk_python_files(root, patterns):
        try:
            # utf-8-sig, not utf-8: a leading BOM is legal and CPython strips
            # it, so plain utf-8 keeps a U+FEFF that ast.parse rejects.
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except SyntaxError:
            skipped.append(SkippedFile(path, "unparseable"))
        except UnicodeDecodeError:
            skipped.append(SkippedFile(path, "undecodable"))
        except OSError:
            skipped.append(SkippedFile(path, "unreadable"))
        else:
            modules.append(ParsedModule(path=path, name=_module_name(path, root), tree=tree))
    # Ordered by module name, since consumers address modules by name rather
    # than by where they happened to fall in the directory walk.
    modules.sort(key=lambda module: module.name)
    skipped.sort(key=lambda skip: skip.path)
    return Project(modules=tuple(modules), skipped=tuple(skipped))


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    if relative.name == "__init__.py":
        return ".".join(relative.parent.parts)
    return ".".join((*relative.parent.parts, relative.stem))

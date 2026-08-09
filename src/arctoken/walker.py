"""Walks a directory tree and collects model call sites from every Python file.

Exclude patterns match directory components only, never filenames, so passing
a file glob such as ``{"*_pb2.py"}`` silently matches nothing. File-glob
excludes are a v0.2 feature.
"""

import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from arctoken.detectors.model_calls import find_model_calls

DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        ".eggs",
        ".git",
        ".mypy_cache",
        ".tox",
        ".venv",
        "*.egg-info",
        "__pycache__",
        "build",
        "dist",
        "env",
        "node_modules",
        "site-packages",
        "tests",
        "venv",
    }
)


@dataclass(frozen=True)
class ModelCall:
    path: Path
    line: int
    pattern: str


@dataclass(frozen=True)
class SkippedFile:
    path: Path
    reason: str


@dataclass
class ScanResult:
    matches: list[ModelCall]
    skipped: list[SkippedFile]


def scan_directory(root: Path, excludes: Iterable[str] | None = None) -> ScanResult:
    patterns = DEFAULT_EXCLUDES if excludes is None else frozenset(excludes)
    matches: list[ModelCall] = []
    skipped: list[SkippedFile] = []
    for path in _walk_python_files(root, patterns):
        try:
            found = find_model_calls(path)
        except SyntaxError:
            skipped.append(SkippedFile(path, "unparseable"))
        except UnicodeDecodeError:
            skipped.append(SkippedFile(path, "undecodable"))
        except OSError:
            skipped.append(SkippedFile(path, "unreadable"))
        else:
            matches.extend(ModelCall(path, line, pattern) for line, pattern in found)
    return ScanResult(matches=matches, skipped=skipped)


def _walk_python_files(root: Path, excludes: frozenset[str]) -> Iterator[Path]:
    # Prune excluded directories in place so os.walk never descends into them;
    # a vendored .venv can hold far more files than the project itself.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not _matches_any(name, excludes))
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            yield Path(dirpath) / filename


def _matches_any(name: str, excludes: frozenset[str]) -> bool:
    return any(fnmatch(name, pattern) for pattern in excludes)

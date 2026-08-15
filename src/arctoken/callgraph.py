"""Builds function-to-function edges and records the loop context of each call.

A call site is either a direct model call or an edge to another function, never
both. The detector's keyword rule matches any call passing ``model=`` and
``messages=``, which includes wrapper functions; treating those as direct calls
would count one real API call twice and drop every edge below the wrapper. So a
call that matches the detector is only a direct call when its name does not
resolve to a function in the project. The keyword shape is a fallback for calls
we cannot resolve, not a competitor to resolution.

One consequence is worth knowing: the same source can classify differently
depending on the scan root. A wrapper inside the tree resolves to an edge, while
the identical wrapper imported from outside it falls back to a direct call,
because there is nothing downstream that could recover the payload.

Names resolve against local functions and the enclosing class first, then
imports, then builtins, which are dropped rather than recorded. Anything left is
an unresolved edge carrying a reason, never a dropped one: claiming a caller
reaches nothing is a guess, and the same one the unknown-receiver case refuses
to make.

Relative imports resolve against the importing module's package, so
``from .llm import ask`` inside ``pkg`` finds ``pkg.llm`` rather than a
top-level ``llm``.

Known v1 limits: inherited and mixin methods are unresolved rather than
followed, and only top-level classes are indexed, so a ``self`` call inside a
nested class is unresolved.
"""

import ast
import builtins
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from arctoken.detectors.model_calls import find_model_call_nodes
from arctoken.project import ParsedModule, Project

MODULE_SCOPE = "<module>"

_SELF_NAMES = frozenset({"self", "cls"})

_LOOP_KINDS: dict[type[ast.AST], str] = {
    ast.For: "for",
    ast.AsyncFor: "for",
    ast.While: "while",
    ast.ListComp: "comprehension",
    ast.SetComp: "comprehension",
    ast.DictComp: "comprehension",
    ast.GeneratorExp: "comprehension",
}


@dataclass(frozen=True)
class Func:
    module: str
    qualname: str


@dataclass(frozen=True)
class UnresolvedCall:
    """A call we could not resolve. Recorded, never dropped."""

    reason: str


@dataclass(frozen=True)
class LoopContext:
    depth: int
    kinds: tuple[str, ...]


@dataclass(frozen=True)
class Edge:
    caller: Func
    callee: Func | UnresolvedCall
    line: int
    loop: LoopContext


@dataclass(frozen=True)
class DirectCall:
    func: Func
    line: int
    pattern: str
    loop: LoopContext


@dataclass(frozen=True)
class CallGraph:
    edges: tuple[Edge, ...]
    direct_calls: tuple[DirectCall, ...]


def build_call_graph(project: Project) -> CallGraph:
    index = _build_index(project)
    edges: list[Edge] = []
    direct_calls: list[DirectCall] = []
    for module in project.modules:
        walker = _ModuleWalker(module, index)
        walker.walk()
        edges.extend(walker.edges)
        direct_calls.extend(walker.direct_calls)
    edges.sort(key=lambda edge: (edge.caller.module, edge.caller.qualname, edge.line))
    direct_calls.sort(key=lambda call: (call.func.module, call.func.qualname, call.line))
    return CallGraph(edges=tuple(edges), direct_calls=tuple(direct_calls))


@dataclass(frozen=True)
class _Index:
    modules: frozenset[str]
    functions: dict[str, frozenset[str]]
    methods: dict[str, dict[str, frozenset[str]]]


def _build_index(project: Project) -> _Index:
    functions: dict[str, frozenset[str]] = {}
    methods: dict[str, dict[str, frozenset[str]]] = {}
    for module in project.modules:
        functions[module.name] = frozenset(
            node.name
            for node in module.tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        )
        methods[module.name] = {
            node.name: frozenset(
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            )
            for node in module.tree.body
            if isinstance(node, ast.ClassDef)
        }
    return _Index(
        modules=frozenset(module.name for module in project.modules),
        functions=functions,
        methods=methods,
    )


class _ModuleWalker:
    def __init__(self, module: ParsedModule, index: _Index) -> None:
        self.module = module
        self.index = index
        self.imported_names, self.imported_modules = _collect_imports(module)
        self.model_calls = {site.node: site.pattern for site in find_model_call_nodes(module.tree)}
        self.scope: list[str] = []
        self.classes: list[str] = []
        self.loops: list[str] = []
        self.edges: list[Edge] = []
        self.direct_calls: list[DirectCall] = []

    def walk(self) -> None:
        self._walk(self.module.tree)

    def _walk(self, node: ast.AST) -> None:
        if isinstance(node, ast.Call):
            self._record_call(node)
        with self._context(node):
            for child in ast.iter_child_nodes(node):
                self._walk(child)

    @contextmanager
    def _context(self, node: ast.AST) -> Iterator[None]:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            self.scope.append(node.name)
            # A def written inside a loop does not run once per iteration.
            outer, self.loops = self.loops, []
            yield
            self.loops = outer
            self.scope.pop()
        elif isinstance(node, ast.ClassDef):
            self.scope.append(node.name)
            self.classes.append(node.name)
            yield
            self.classes.pop()
            self.scope.pop()
        else:
            kind = _LOOP_KINDS.get(type(node))
            if kind is None:
                yield
            else:
                self.loops.append(kind)
                yield
                self.loops.pop()

    def _record_call(self, node: ast.Call) -> None:
        target = self._resolve(node.func)
        if target is None:
            return
        caller = Func(self.module.name, ".".join(self.scope) or MODULE_SCOPE)
        loop = LoopContext(depth=len(self.loops), kinds=tuple(self.loops))
        pattern = self.model_calls.get(node)
        if pattern is not None and not isinstance(target, Func):
            self.direct_calls.append(
                DirectCall(func=caller, line=node.lineno, pattern=pattern, loop=loop)
            )
        else:
            self.edges.append(Edge(caller=caller, callee=target, line=node.lineno, loop=loop))

    def _resolve(self, func: ast.expr) -> Func | UnresolvedCall | None:
        if isinstance(func, ast.Name):
            return self._resolve_name(func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return self._resolve_receiver(func.value.id, func.attr)
        return UnresolvedCall("unknown-receiver")

    def _resolve_name(self, name: str) -> Func | UnresolvedCall | None:
        if name in self.index.functions[self.module.name]:
            return Func(self.module.name, name)
        if name in self.imported_names:
            module_name, original = self.imported_names[name]
            return self._from_module(module_name, original)
        if hasattr(builtins, name):
            # A builtin cannot reach a model call, and nearly every function
            # calls one. Recording them would bury the unresolved edges.
            return None
        return UnresolvedCall("unknown-name")

    def _resolve_receiver(self, receiver: str, attr: str) -> Func | UnresolvedCall:
        if receiver in _SELF_NAMES and self.classes:
            enclosing = self.classes[-1]
            if attr in self.index.methods[self.module.name].get(enclosing, frozenset()):
                return Func(self.module.name, f"{enclosing}.{attr}")
            return UnresolvedCall("unknown-method")
        if receiver in self.imported_modules:
            return self._from_module(self.imported_modules[receiver], attr)
        return UnresolvedCall("unknown-receiver")

    def _from_module(self, module_name: str, attr: str) -> Func | UnresolvedCall:
        if module_name in self.index.modules:
            return Func(module_name, attr)
        return UnresolvedCall("outside-tree")


def _collect_imports(
    module: ParsedModule,
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    names: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    package = _package_of(module)
    for node in ast.walk(module.tree):
        if isinstance(node, ast.ImportFrom):
            base = _absolute_base(package, node)
            for alias in node.names:
                names[alias.asname or alias.name] = (base, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                modules[alias.asname or root] = root
    return names, modules


def _package_of(module: ParsedModule) -> list[str]:
    """The dotted package a module lives in. A package is its own container."""
    parts = module.name.split(".")
    if module.path.name == "__init__.py":
        return parts
    return parts[:-1]


def _absolute_base(package: list[str], node: ast.ImportFrom) -> str:
    """Resolve ``from .x import y`` against the importing module's package.

    Ignoring ``level`` would make ``from .llm import ask`` inside ``pkg`` look
    up a top-level ``llm``, which either resolves to nothing or, worse, to a
    different module of that name -- a confidently wrong edge.
    """
    climbed = package[: max(0, len(package) - (node.level - 1))] if node.level else []
    named = [node.module] if node.module else []
    return ".".join([*climbed, *named])

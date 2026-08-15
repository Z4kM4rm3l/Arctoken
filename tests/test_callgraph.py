from pathlib import Path

from arctoken.callgraph import (
    DirectCall,
    Edge,
    Func,
    LoopContext,
    Reaching,
    UnresolvedCall,
    build_call_graph,
)
from arctoken.project import Project, load_project

NO_LOOP = LoopContext(depth=0, kinds=())

LLM_CLIENT = """
def ask(prompt):
    return client.messages.create(
        model="claude-3",
        messages=[{"role": "user", "content": prompt}],
    )
"""

AGENT = """
from llm_client import ask


def step(item):
    return ask(item)


def run(items):
    for item in items:
        step(item)
"""

CLASS_METHODS = """
class Agent:
    def ask(self, prompt):
        return client.messages.create(model="m", messages=[])

    def run(self, items):
        for item in items:
            self.ask(item)
"""

MISSING_METHOD = """
class Agent:
    def run(self, items):
        self.ask(items)
"""

UNKNOWN_RECEIVER = """
def run(client):
    return client.ask("hi")
"""

IMPORT_FORMS = """
import llm_client
from llm_client import ask


def via_module():
    return llm_client.ask("hi")


def via_name():
    return ask("hi")
"""

OUTSIDE_TREE = """
from anthropic import Anthropic


def build():
    return Anthropic()
"""

BARE_UNKNOWN_NAME = """
def run():
    return handler()
"""

BUILTIN_AND_LOCAL = """
def run(items):
    len(items)
    helper()


def helper():
    pass
"""

WRAPPER_WITH_KWARG_SHAPE = """
def ask(model, messages):
    return client.messages.create(model=model, messages=messages)


def run(items):
    for item in items:
        ask(model="m", messages=[item])
"""

VENDOR_WRAPPER = """
from vendor_helpers import ask


def run(items):
    for item in items:
        ask(model="m", messages=[item])
"""

SHADOWED_BUILTIN = """
def filter(items):
    return client.messages.create(model="m", messages=items)


def run(items):
    return filter(items)
"""

MODULE_SCOPE = """
client.messages.create(model="m", messages=[])
helper()


def helper():
    pass
"""

ORDERING = """
def zzz():
    helper()
    client.messages.create(model="m", messages=[])


def aaa():
    helper()
    client.messages.create(model="m", messages=[])


def helper():
    pass
"""

CYCLE = """
def a():
    b()


def b():
    client.messages.create(model="m", messages=[])
    a()
"""

SELF_RECURSION = """
def f(n):
    client.messages.create(model="m", messages=[])
    f(n - 1)
"""

NOT_REACHING = """
def reaches():
    client.messages.create(model="m", messages=[])


def calls_unresolved(client):
    return client.send()


def calls_a_dead_end():
    return helper()


def helper():
    pass
"""

SKIPPED_CALLER = """
def aaa():
    client.messages.create(model="m", messages=[])
    leaf()


def zzz():
    leaf()


def leaf():
    client.messages.create(model="m", messages=[])
"""

EQUAL_PATHS = """
def top():
    zzz()
    aaa()


def aaa():
    leaf()


def zzz():
    leaf()


def leaf():
    client.messages.create(model="m", messages=[])
"""

TWO_PATHS = """
def top():
    leaf()
    middle()


def middle():
    leaf()


def leaf():
    client.messages.create(model="m", messages=[])
"""

NOT_IN_A_LOOP = """
def once():
    client.messages.create(model="m", messages=[])
"""

NESTED_LOOPS = """
def nested(rows):
    while True:
        for row in rows:
            client.messages.create(model="m", messages=[])
"""

COMPREHENSION = """
def fan_out(items):
    return [client.messages.create(model="m", messages=[]) for item in items]
"""


CHAINED_RECEIVER = """
def run(session):
    return session.http.close()
"""

METHOD_CALLS_OTHER_RECEIVER = """
class Agent:
    def run(self, helper):
        return helper.execute()
"""

NESTED_CLASS = """
class Outer:
    class Inner:
        def run(self):
            return self.missing()
"""

DOTTED_IMPORT_ROOT = """
import pkg.llm


def run():
    return pkg.helper()
"""


def project_from(root: Path, **modules: str) -> Project:
    for name, source in modules.items():
        (root / f"{name}.py").write_text(source)
    return load_project(root)


def graph_of(root: Path, **modules: str):
    return build_call_graph(project_from(root, **modules))


def package_graph(root: Path, files: dict[str, str]):
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return build_call_graph(load_project(root))


# --- edges and resolution --------------------------------------------------


def test_call_to_a_function_in_the_same_module_is_an_edge(tmp_path):
    graph = graph_of(tmp_path, solo=TWO_PATHS)

    assert Edge(
        caller=Func("solo", "middle"),
        callee=Func("solo", "leaf"),
        line=8,
        loop=NO_LOOP,
    ) in list(graph.edges)


def test_wrapper_matching_the_kwarg_shape_is_an_edge_not_a_direct_call(tmp_path):
    # ask(model=..., messages=...) matches the detector's kwarg rule, but the
    # name resolves to a project function. Calling it a direct call would
    # count one real API call twice and drop everything below the wrapper.
    graph = graph_of(tmp_path, app=WRAPPER_WITH_KWARG_SHAPE)

    assert list(graph.direct_calls) == [
        DirectCall(
            func=Func("app", "ask"),
            line=3,
            pattern=".messages.create",
            loop=NO_LOOP,
        )
    ]
    assert list(graph.edges) == [
        Edge(
            caller=Func("app", "run"),
            callee=Func("app", "ask"),
            line=8,
            loop=LoopContext(depth=1, kinds=("for",)),
        )
    ]


def test_self_method_call_resolves_to_the_enclosing_class(tmp_path):
    # self.ask() needs the enclosing class, which is lexical, not a type.
    graph = graph_of(tmp_path, service=CLASS_METHODS)

    assert list(graph.edges) == [
        Edge(
            caller=Func("service", "Agent.run"),
            callee=Func("service", "Agent.ask"),
            line=8,
            loop=LoopContext(depth=1, kinds=("for",)),
        )
    ]


def test_self_method_missing_from_the_class_is_an_unresolved_edge(tmp_path):
    # Inherited and mixin methods are common. Dropping the edge would claim
    # the caller reaches nothing, which is the same guess unknown-receiver
    # correctly refuses to make.
    graph = graph_of(tmp_path, service=MISSING_METHOD)

    assert list(graph.edges) == [
        Edge(
            caller=Func("service", "Agent.run"),
            callee=UnresolvedCall("unknown-method"),
            line=4,
            loop=NO_LOOP,
        )
    ]


def test_call_on_an_unknown_receiver_is_an_unresolved_edge(tmp_path):
    # Resolving client.ask() would need type inference. Dropping the edge
    # would instead claim the caller reaches nothing, which is a guess.
    graph = graph_of(tmp_path, mystery=UNKNOWN_RECEIVER)

    assert list(graph.edges) == [
        Edge(
            caller=Func("mystery", "run"),
            callee=UnresolvedCall("unknown-receiver"),
            line=3,
            loop=NO_LOOP,
        )
    ]


def test_both_import_forms_resolve_across_files(tmp_path):
    graph = graph_of(tmp_path, llm_client=LLM_CLIENT, caller=IMPORT_FORMS)

    assert [edge for edge in graph.edges if edge.caller.module == "caller"] == [
        Edge(
            caller=Func("caller", "via_module"),
            callee=Func("llm_client", "ask"),
            line=7,
            loop=NO_LOOP,
        ),
        Edge(
            caller=Func("caller", "via_name"),
            callee=Func("llm_client", "ask"),
            line=11,
            loop=NO_LOOP,
        ),
    ]


def test_name_imported_from_outside_the_scanned_tree_is_unresolved(tmp_path):
    graph = graph_of(tmp_path, uses_sdk=OUTSIDE_TREE)

    assert list(graph.edges) == [
        Edge(
            caller=Func("uses_sdk", "build"),
            callee=UnresolvedCall("outside-tree"),
            line=6,
            loop=NO_LOOP,
        )
    ]


def test_bare_name_that_resolves_to_nothing_is_unresolved(tmp_path):
    graph = graph_of(tmp_path, mystery=BARE_UNKNOWN_NAME)

    assert list(graph.edges) == [
        Edge(
            caller=Func("mystery", "run"),
            callee=UnresolvedCall("unknown-name"),
            line=3,
            loop=NO_LOOP,
        )
    ]


def test_builtin_calls_produce_no_edge_at_all(tmp_path):
    # A builtin cannot reach a model call, and every function calls a few.
    # Recording them would bury the unresolved edges that actually matter.
    graph = graph_of(tmp_path, app=BUILTIN_AND_LOCAL)

    assert list(graph.edges) == [
        Edge(
            caller=Func("app", "run"),
            callee=Func("app", "helper"),
            line=4,
            loop=NO_LOOP,
        )
    ]


def test_kwarg_shape_resolving_outside_the_tree_stays_a_direct_call(tmp_path):
    # We cannot see inside vendor_helpers, so the kwarg shape is the best
    # evidence available; an outside-tree edge would lose the payload with
    # nothing downstream able to recover it.
    graph = graph_of(tmp_path, app=VENDOR_WRAPPER)

    assert list(graph.direct_calls) == [
        DirectCall(
            func=Func("app", "run"),
            line=7,
            pattern="model=+messages=",
            loop=LoopContext(depth=1, kinds=("for",)),
        )
    ]
    assert list(graph.edges) == []


def test_local_function_shadowing_a_builtin_still_produces_an_edge(tmp_path):
    # Local functions and imports are consulted before builtins, so a
    # user-defined filter() is not silently skipped as if it were the builtin.
    graph = graph_of(tmp_path, app=SHADOWED_BUILTIN)

    assert list(graph.edges) == [
        Edge(
            caller=Func("app", "run"),
            callee=Func("app", "filter"),
            line=7,
            loop=NO_LOOP,
        )
    ]
    assert [call.func for call in graph.direct_calls] == [Func("app", "filter")]


def test_module_scope_calls_belong_to_a_synthetic_module_function(tmp_path):
    # Import-time model calls are real cost, and the walker already reports
    # them, so the graph needs somewhere to put them.
    graph = graph_of(tmp_path, script=MODULE_SCOPE)

    assert list(graph.direct_calls) == [
        DirectCall(
            func=Func("script", "<module>"),
            line=2,
            pattern=".messages.create",
            loop=NO_LOOP,
        )
    ]
    assert list(graph.edges) == [
        Edge(
            caller=Func("script", "<module>"),
            callee=Func("script", "helper"),
            line=3,
            loop=NO_LOOP,
        )
    ]


def test_edges_and_direct_calls_are_ordered_by_qualified_name(tmp_path):
    # Both lists hold more than one entry, and source order is the reverse of
    # sorted order, so the ordering is actually exercised.
    graph = graph_of(tmp_path, app=ORDERING)

    assert [(edge.caller, edge.line) for edge in graph.edges] == [
        (Func("app", "aaa"), 8),
        (Func("app", "zzz"), 3),
    ]
    assert [(call.func, call.line) for call in graph.direct_calls] == [
        (Func("app", "aaa"), 9),
        (Func("app", "zzz"), 4),
    ]


def test_chained_receiver_is_unresolved_with_a_reason(tmp_path):
    # session.http.close() has an Attribute receiver rather than a Name, so it
    # never reaches receiver resolution. Its reason is only observable on a
    # call that is not itself a model call.
    graph = graph_of(tmp_path, app=CHAINED_RECEIVER)

    assert list(graph.edges) == [
        Edge(
            caller=Func("app", "run"),
            callee=UnresolvedCall("unknown-receiver"),
            line=3,
            loop=NO_LOOP,
        )
    ]


def test_method_calling_a_non_self_receiver_is_not_treated_as_a_self_call(tmp_path):
    # Inside a class, a receiver that is not self must still fall through to
    # receiver resolution rather than being looked up among the class methods.
    graph = graph_of(tmp_path, service=METHOD_CALLS_OTHER_RECEIVER)

    assert list(graph.edges) == [
        Edge(
            caller=Func("service", "Agent.run"),
            callee=UnresolvedCall("unknown-receiver"),
            line=4,
            loop=NO_LOOP,
        )
    ]


def test_self_call_inside_a_nested_class_is_unresolved(tmp_path):
    # Only top-level classes are indexed, so a nested class has no method set
    # at all. That must read as unknown-method, not crash.
    graph = graph_of(tmp_path, service=NESTED_CLASS)

    assert list(graph.edges) == [
        Edge(
            caller=Func("service", "Outer.Inner.run"),
            callee=UnresolvedCall("unknown-method"),
            line=5,
            loop=NO_LOOP,
        )
    ]


def test_dotted_import_binds_only_its_root_name(tmp_path):
    # "import pkg.llm" binds pkg, so pkg.helper() resolves through the root.
    graph = package_graph(
        tmp_path,
        {
            "pkg/__init__.py": "def helper():\n    pass\n",
            "pkg/llm.py": "",
            "app.py": DOTTED_IMPORT_ROOT,
        },
    )

    assert list(graph.edges) == [
        Edge(
            caller=Func("app", "run"),
            callee=Func("pkg", "helper"),
            line=6,
            loop=NO_LOOP,
        )
    ]


def test_relative_import_resolves_inside_its_own_package(tmp_path):
    # The decoy top-level llm.py is what makes this a real test: resolving
    # ".llm" as "llm" produces a confidently wrong edge, not a missing one.
    graph = package_graph(
        tmp_path,
        {
            "llm.py": "def ask():\n    pass\n",
            "pkg/__init__.py": "",
            "pkg/llm.py": "def ask():\n    pass\n",
            "pkg/agent.py": "from .llm import ask\n\n\ndef run():\n    return ask()\n",
        },
    )

    assert list(graph.edges) == [
        Edge(
            caller=Func("pkg.agent", "run"),
            callee=Func("pkg.llm", "ask"),
            line=5,
            loop=NO_LOOP,
        )
    ]


def test_relative_import_walks_up_one_package_per_extra_dot(tmp_path):
    graph = package_graph(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/llm.py": "def ask():\n    pass\n",
            "pkg/sub/__init__.py": "",
            "pkg/sub/agent.py": "from ..llm import ask\n\n\ndef run():\n    return ask()\n",
        },
    )

    assert list(graph.edges) == [
        Edge(
            caller=Func("pkg.sub.agent", "run"),
            callee=Func("pkg.llm", "ask"),
            line=5,
            loop=NO_LOOP,
        )
    ]


def test_relative_import_from_a_package_init_and_without_a_module_name(tmp_path):
    # An __init__ is itself the package, so ".llm" is a sibling rather than a
    # child. "from . import helper" carries no module name at all.
    graph = package_graph(
        tmp_path,
        {
            "pkg/__init__.py": "from .llm import ask\n\n\ndef helper():\n    return ask()\n",
            "pkg/llm.py": "def ask():\n    pass\n",
            "pkg/agent.py": "from . import helper\n\n\ndef run():\n    return helper()\n",
        },
    )

    assert list(graph.edges) == [
        Edge(
            caller=Func("pkg", "helper"),
            callee=Func("pkg.llm", "ask"),
            line=5,
            loop=NO_LOOP,
        ),
        Edge(
            caller=Func("pkg.agent", "run"),
            callee=Func("pkg", "helper"),
            line=5,
            loop=NO_LOOP,
        ),
    ]


def test_relative_import_climbing_above_the_scan_root_is_outside_the_tree(tmp_path):
    # pkg/llm.py exists, so wrapping back into the package instead of climbing
    # out would silently produce a resolved edge to the wrong module. The
    # target is real but unscanned, which is outside-tree rather than
    # unknown-name: the user should raise the scan root, not assume a failure.
    graph = package_graph(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/llm.py": "def ask():\n    pass\n",
            "pkg/agent.py": "from ..llm import ask\n\n\ndef run():\n    return ask()\n",
        },
    )

    assert list(graph.edges) == [
        Edge(
            caller=Func("pkg.agent", "run"),
            callee=UnresolvedCall("outside-tree"),
            line=5,
            loop=NO_LOOP,
        )
    ]


def test_relative_import_of_a_multi_segment_module_resolves(tmp_path):
    graph = package_graph(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/sub/__init__.py": "",
            "pkg/sub/llm.py": "def ask():\n    pass\n",
            "pkg/agent.py": "from .sub.llm import ask\n\n\ndef run():\n    return ask()\n",
        },
    )

    assert list(graph.edges) == [
        Edge(
            caller=Func("pkg.agent", "run"),
            callee=Func("pkg.sub.llm", "ask"),
            line=5,
            loop=NO_LOOP,
        )
    ]


# --- loop context ----------------------------------------------------------


def test_call_outside_any_loop_has_zero_depth(tmp_path):
    graph = graph_of(tmp_path, plain=NOT_IN_A_LOOP)

    assert list(graph.direct_calls) == [
        DirectCall(
            func=Func("plain", "once"),
            line=3,
            pattern=".messages.create",
            loop=NO_LOOP,
        )
    ]


def test_nested_loops_record_depth_and_kinds_outermost_first(tmp_path):
    graph = graph_of(tmp_path, nested=NESTED_LOOPS)

    assert list(graph.direct_calls) == [
        DirectCall(
            func=Func("nested", "nested"),
            line=5,
            pattern=".messages.create",
            loop=LoopContext(depth=2, kinds=("while", "for")),
        )
    ]


def test_comprehension_counts_as_a_loop(tmp_path):
    # [create(...) for item in items] fans out exactly like a for loop.
    graph = graph_of(tmp_path, comp=COMPREHENSION)

    assert list(graph.direct_calls) == [
        DirectCall(
            func=Func("comp", "fan_out"),
            line=3,
            pattern=".messages.create",
            loop=LoopContext(depth=1, kinds=("comprehension",)),
        )
    ]


def test_edge_carries_the_loop_context_of_the_call_not_the_callee(tmp_path):
    # The multiplier lives where the wrapper is called, not where the model
    # call is written, so the edge is what has to carry it.
    graph = graph_of(tmp_path, llm_client=LLM_CLIENT, agent=AGENT)

    run_to_step = next(edge for edge in graph.edges if edge.caller == Func("agent", "run"))
    assert run_to_step.loop == LoopContext(depth=1, kinds=("for",))

    ask_call = next(call for call in graph.direct_calls)
    assert ask_call.func == Func("llm_client", "ask")
    assert ask_call.loop == NO_LOOP


# --- transitive propagation ------------------------------------------------


def test_reaching_records_depth_and_path_across_files(tmp_path):
    # A three-link chain, so the path has an element with entries on both
    # sides of it rather than only ends.
    graph = graph_of(tmp_path, llm_client=LLM_CLIENT, agent=AGENT)

    assert list(graph.reaching) == [
        Reaching(
            func=Func("agent", "run"),
            depth=2,
            path=(Func("agent", "run"), Func("agent", "step"), Func("llm_client", "ask")),
        ),
        Reaching(
            func=Func("agent", "step"),
            depth=1,
            path=(Func("agent", "step"), Func("llm_client", "ask")),
        ),
        Reaching(
            func=Func("llm_client", "ask"),
            depth=0,
            path=(Func("llm_client", "ask"),),
        ),
    ]


def test_mutual_recursion_terminates(tmp_path):
    graph = graph_of(tmp_path, ring=CYCLE)

    assert list(graph.reaching) == [
        Reaching(func=Func("ring", "a"), depth=1, path=(Func("ring", "a"), Func("ring", "b"))),
        Reaching(func=Func("ring", "b"), depth=0, path=(Func("ring", "b"),)),
    ]


def test_direct_recursion_terminates(tmp_path):
    graph = graph_of(tmp_path, loopy=SELF_RECURSION)

    assert list(graph.reaching) == [
        Reaching(func=Func("loopy", "f"), depth=0, path=(Func("loopy", "f"),))
    ]


def test_shortest_path_wins_when_two_paths_exist(tmp_path):
    # top reaches leaf directly and also through middle; the direct hop is
    # the honest depth.
    graph = graph_of(tmp_path, solo=TWO_PATHS)

    assert [(reaching.func, reaching.depth) for reaching in graph.reaching] == [
        (Func("solo", "leaf"), 0),
        (Func("solo", "middle"), 1),
        (Func("solo", "top"), 1),
    ]
    top = next(item for item in graph.reaching if item.func == Func("solo", "top"))
    assert top.path == (Func("solo", "top"), Func("solo", "leaf"))


def test_equal_length_paths_break_the_tie_on_qualified_name(tmp_path):
    # top reaches leaf through both aaa and zzz at the same depth, so without
    # a tie-break the recorded path would follow edge discovery order.
    graph = graph_of(tmp_path, solo=EQUAL_PATHS)

    assert [(reaching.func, reaching.depth) for reaching in graph.reaching] == [
        (Func("solo", "aaa"), 1),
        (Func("solo", "leaf"), 0),
        (Func("solo", "top"), 2),
        (Func("solo", "zzz"), 1),
    ]
    top = next(item for item in graph.reaching if item.func == Func("solo", "top"))
    assert top.path == (Func("solo", "top"), Func("solo", "aaa"), Func("solo", "leaf"))


def test_functions_that_reach_nothing_are_absent(tmp_path):
    # An unresolved callee cannot be followed, so calls_unresolved must not be
    # reported as reaching; saying otherwise would be a guess. calls_a_dead_end
    # resolves fine but its callee reaches nothing.
    graph = graph_of(tmp_path, app=NOT_REACHING)

    assert list(graph.reaching) == [
        Reaching(func=Func("app", "reaches"), depth=0, path=(Func("app", "reaches"),))
    ]


def test_an_already_reached_caller_does_not_hide_the_callers_after_it(tmp_path):
    # leaf's callers are [aaa, zzz]. aaa is already a seed, so a loop that
    # stopped at the first visited caller would never record zzz at all --
    # under-reporting silently rather than failing visibly.
    graph = graph_of(tmp_path, app=SKIPPED_CALLER)

    assert list(graph.reaching) == [
        Reaching(func=Func("app", "aaa"), depth=0, path=(Func("app", "aaa"),)),
        Reaching(func=Func("app", "leaf"), depth=0, path=(Func("app", "leaf"),)),
        Reaching(func=Func("app", "zzz"), depth=1, path=(Func("app", "zzz"), Func("app", "leaf"))),
    ]

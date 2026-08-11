import ast

from arctoken.payloads import (
    Derived,
    Partial,
    Payload,
    Resolved,
    Unresolved,
    extract_payloads,
)


def payloads(source: str) -> list[Payload]:
    return extract_payloads(ast.parse(source))


LITERAL_SYSTEM = """
client.messages.create(
    model="claude-3",
    system="You are a careful assistant.",
    messages=[{"role": "user", "content": "hi"}],
    max_tokens=1024,
)
"""

CONSTANT_SYSTEM = """
SYSTEM_PROMPT = "You are a careful assistant."

client.messages.create(
    model="claude-3",
    system=SYSTEM_PROMPT,
    messages=[],
)
"""

FSTRING_SYSTEM = """
client.messages.create(
    model="claude-3",
    system=f"You are {role}. Answer in {language}.",
    messages=[],
)
"""

SPREAD = """
client.chat.completions.create(**payload)
"""

PARTIAL_SPREAD = """
client.chat.completions.create(model="gpt-4", **rest)
"""

TOOLS_FROM_CALL = """
client.messages.create(
    model="claude-3",
    tools=build_tools(),
    messages=[],
)
"""

PARTLY_DYNAMIC_TOOLS = """
client.messages.create(
    model="claude-3",
    tools=[
        {"name": "search", "description": "Search the web."},
        build_extra_tool(),
    ],
    messages=[],
)
"""

OPENAI_SHAPE = """
client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "hi"},
    ],
)
"""

CONCATENATED_SYSTEM = """
client.messages.create(
    model="claude-3",
    system="You are " + role + ".",
    messages=[],
)
"""

STATIC_FSTRING_SYSTEM = """
client.messages.create(
    model="claude-3",
    system=f"static only",
    messages=[],
)
"""

IMPORTED_SYSTEM = """
from config import SYSTEM

client.messages.create(
    model="claude-3",
    system=SYSTEM,
    messages=[],
)
"""

RUNTIME_NAME_SYSTEM = """
client.messages.create(
    model="claude-3",
    system=SOMETHING,
    messages=[],
)
"""

UNSUPPORTED_MAX_TOKENS = """
client.messages.create(
    model="claude-3",
    messages=[],
    max_tokens=limit * 2,
)
"""

MESSAGES_FROM_CALL = """
client.chat.completions.create(
    model="gpt-4",
    messages=load_history(),
)
"""

SYSTEM_MESSAGE_NOT_FIRST = """
CLIENT = make_client()
FIRST, SECOND = 1, 2

CLIENT.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "You are terse."},
    ],
)
"""


def test_literal_system_prompt_resolves():
    assert payloads(LITERAL_SYSTEM) == [
        Payload(
            line=2,
            model=Resolved("claude-3"),
            system=Resolved("You are a careful assistant."),
            tools=None,
            messages=Resolved([{"role": "user", "content": "hi"}]),
            max_tokens=Resolved(1024),
        )
    ]


def test_module_level_constant_resolves_to_its_literal():
    assert payloads(CONSTANT_SYSTEM) == [
        Payload(
            line=4,
            model=Resolved("claude-3"),
            system=Resolved("You are a careful assistant."),
            tools=None,
            messages=Resolved([]),
            max_tokens=None,
        )
    ]


def test_fstring_system_prompt_keeps_static_parts_and_marks_holes():
    # None marks an interpolation whose value we cannot read.
    assert payloads(FSTRING_SYSTEM) == [
        Payload(
            line=2,
            model=Resolved("claude-3"),
            system=Partial(("You are ", None, ". Answer in ", None, ".")),
            tools=None,
            messages=Resolved([]),
            max_tokens=None,
        )
    ]


def test_spread_makes_every_unseen_field_unresolved_not_absent():
    # A ** spread may well carry system/tools/messages, so none of them can be
    # claimed absent. Absent means "definitely not sent"; this is "unreadable".
    assert payloads(SPREAD) == [
        Payload(
            line=2,
            model=Unresolved("spread"),
            system=Unresolved("spread"),
            tools=Unresolved("spread"),
            messages=Unresolved("spread"),
            max_tokens=Unresolved("spread"),
        )
    ]


def test_partial_spread_resolves_explicit_kwargs_and_marks_the_rest_unresolved():
    # model is written out, so it is readable; the other four could be hiding
    # in **rest and must not be reported absent.
    assert payloads(PARTIAL_SPREAD) == [
        Payload(
            line=2,
            model=Resolved("gpt-4"),
            system=Unresolved("spread"),
            tools=Unresolved("spread"),
            messages=Unresolved("spread"),
            max_tokens=Unresolved("spread"),
        )
    ]


def test_tools_built_by_a_function_call_are_unresolved():
    # build_tools() is itself a Call node, but it is not a model call site,
    # so exactly one payload comes back. The list is not a literal at all,
    # so there is nothing to keep.
    assert payloads(TOOLS_FROM_CALL) == [
        Payload(
            line=2,
            model=Resolved("claude-3"),
            system=None,
            tools=Unresolved("function-call"),
            messages=Resolved([]),
            max_tokens=None,
        )
    ]


def test_partly_dynamic_tools_list_keeps_the_readable_schemas():
    # The list IS a literal, so the readable tool schema survives and only the
    # one unreadable element becomes a hole. Discarding the whole list here
    # would throw away most of the tokens we are trying to count.
    assert payloads(PARTLY_DYNAMIC_TOOLS) == [
        Payload(
            line=2,
            model=Resolved("claude-3"),
            system=None,
            tools=Partial(
                (
                    {"name": "search", "description": "Search the web."},
                    None,
                )
            ),
            messages=Resolved([]),
            max_tokens=None,
        )
    ]


def test_concatenation_keeps_static_parts_and_marks_holes():
    assert payloads(CONCATENATED_SYSTEM) == [
        Payload(
            line=2,
            model=Resolved("claude-3"),
            system=Partial(("You are ", None, ".")),
            tools=None,
            messages=Resolved([]),
            max_tokens=None,
        )
    ]


def test_fstring_without_interpolations_is_fully_resolved():
    # No holes means nothing was lost, so this is not Partial.
    assert payloads(STATIC_FSTRING_SYSTEM) == [
        Payload(
            line=2,
            model=Resolved("claude-3"),
            system=Resolved("static only"),
            tools=None,
            messages=Resolved([]),
            max_tokens=None,
        )
    ]


def test_name_imported_from_another_module_is_unresolved():
    assert payloads(IMPORTED_SYSTEM) == [
        Payload(
            line=4,
            model=Resolved("claude-3"),
            system=Unresolved("imported-name"),
            tools=None,
            messages=Resolved([]),
            max_tokens=None,
        )
    ]


def test_name_with_no_module_level_literal_is_unresolved():
    assert payloads(RUNTIME_NAME_SYSTEM) == [
        Payload(
            line=2,
            model=Resolved("claude-3"),
            system=Unresolved("runtime-name"),
            tools=None,
            messages=Resolved([]),
            max_tokens=None,
        )
    ]


def test_arithmetic_expression_is_unresolved():
    assert payloads(UNSUPPORTED_MAX_TOKENS) == [
        Payload(
            line=2,
            model=Resolved("claude-3"),
            system=None,
            tools=None,
            messages=Resolved([]),
            max_tokens=Unresolved("unsupported-expression"),
        )
    ]


def test_unreadable_messages_yield_no_derived_system():
    # Nothing can be lifted out of a messages list we cannot read, and the
    # absent system kwarg must not be invented from it.
    assert payloads(MESSAGES_FROM_CALL) == [
        Payload(
            line=2,
            model=Resolved("gpt-4"),
            system=None,
            tools=None,
            messages=Unresolved("function-call"),
            max_tokens=None,
        )
    ]


def test_system_message_is_found_when_it_is_not_the_first_message():
    # Also exercises module-level assignments that cannot be constants: a
    # non-literal value, and a tuple target.
    assert payloads(SYSTEM_MESSAGE_NOT_FIRST) == [
        Payload(
            line=5,
            model=Resolved("gpt-4"),
            system=Derived(Resolved("You are terse.")),
            tools=None,
            messages=Resolved(
                [
                    {"role": "user", "content": "hi"},
                    {"role": "system", "content": "You are terse."},
                ]
            ),
            max_tokens=None,
        )
    ]


def test_openai_system_message_inside_messages_is_marked_derived():
    # system is wrapped in Derived so a consumer cannot read it without
    # seeing that the same text is already counted inside messages.
    assert payloads(OPENAI_SHAPE) == [
        Payload(
            line=2,
            model=Resolved("gpt-4"),
            system=Derived(Resolved("You are terse.")),
            tools=None,
            messages=Resolved(
                [
                    {"role": "system", "content": "You are terse."},
                    {"role": "user", "content": "hi"},
                ]
            ),
            max_tokens=None,
        )
    ]

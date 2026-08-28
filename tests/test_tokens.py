from arctoken.tokens import (
    Counted,
    DerivedWeight,
    HeuristicStrategy,
    NotCounted,
    PartiallyCounted,
    PayloadWeight,
    weigh_payload,
)

from arctoken.payloads import Derived, Partial, Payload, Resolved, Unresolved


class FakeStrategy:
    """Ten tokens per whitespace-separated chunk, so every sum is hand-checkable."""

    name = "fake"
    exact = False

    def count(self, text: str) -> int:
        return 10 * len(text.split())


class DoubleFakeStrategy:
    name = "double-fake"
    exact = False

    def count(self, text: str) -> int:
        return 20 * len(text.split())


def payload(**fields: object) -> Payload:
    base: dict[str, object] = {
        "line": 1,
        "model": None,
        "system": None,
        "tools": None,
        "messages": None,
        "max_tokens": None,
    }
    base.update(fields)
    return Payload(**base)  # type: ignore[arg-type]  # test helper builds a valid shape


def test_resolved_value_is_counted():
    # "You are a careful assistant" is five chunks.
    weight = weigh_payload(payload(system=Resolved("You are a careful assistant")), FakeStrategy())

    assert weight == PayloadWeight(line=1, system=Counted(50), tools=None, messages=None)


def test_partial_counts_each_static_part_separately_and_records_every_hole():
    # "pre", "mid" and "fix" are not adjacent in the real string; unknown text
    # sits between them. Joining first would count one chunk instead of three,
    # and there are two holes rather than merely some.
    weight = weigh_payload(
        payload(system=Partial(("pre", None, "mid", None, "fix"))), FakeStrategy()
    )

    assert weight.system == PartiallyCounted(tokens=30, unknowns=2)


def test_unresolved_gets_no_count_rather_than_zero():
    # Zero would claim the field costs nothing, which is the guess the whole
    # payload layer exists to refuse.
    weight = weigh_payload(payload(tools=Unresolved("function-call")), FakeStrategy())

    assert weight.tools == NotCounted("function-call")


def test_absent_field_has_no_weight_at_all():
    weight = weigh_payload(payload(system=Resolved("hi")), FakeStrategy())

    assert weight.tools is None
    assert weight.messages is None


def test_derived_weight_stays_wrapped_so_it_cannot_be_double_counted():
    weight = weigh_payload(
        payload(
            system=Derived(Resolved("hello there friend")),
            messages=Resolved([{"role": "system", "content": "hello there friend"}]),
        ),
        FakeStrategy(),
    )

    assert weight.system == DerivedWeight(Counted(30))


def test_structured_value_is_serialised_to_wire_json_before_counting():
    # Compact JSON of two messages is three whitespace-separated chunks:
    # [{"role":"user","content":"hello there"},{"role":"assistant",...:"hi back"}]
    weight = weigh_payload(
        payload(
            messages=Resolved(
                [
                    {"role": "user", "content": "hello there"},
                    {"role": "assistant", "content": "hi back"},
                ]
            )
        ),
        FakeStrategy(),
    )

    assert weight.messages == Counted(30)


def test_counting_strategy_is_injectable():
    same = payload(system=Resolved("You are a careful assistant"))

    assert weigh_payload(same, FakeStrategy()).system == Counted(50)
    assert weigh_payload(same, DoubleFakeStrategy()).system == Counted(100)


def test_heuristic_counts_word_runs_and_punctuation_runs_separately():
    # "hello" (5 chars) -> 2, "," -> 1, "world" (5 chars) -> 2.
    assert HeuristicStrategy().count("hello, world") == 5


def test_heuristic_charges_json_punctuation_a_flat_divisor_would_miss():
    # Both strings are 17 characters, so a flat chars/4 divisor would score
    # them identically at 5. Tool schemas are the JSON-dense side of exactly
    # the prose-versus-schema comparison the headline finding rests on.
    schema = '{"name":"search"}'
    prose = "x" * len(schema)

    assert HeuristicStrategy().count(schema) == 7
    assert HeuristicStrategy().count(prose) == 5


def test_default_strategy_declares_itself_inexact():
    # No local Anthropic tokenizer exists, so the shipped default must never
    # let a report present its numbers as measurements.
    assert HeuristicStrategy().exact is False
    assert HeuristicStrategy().name

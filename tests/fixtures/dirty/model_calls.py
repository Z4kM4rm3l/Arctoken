"""Fixture: genuine model call sites, one per function."""

import openai

client = openai.OpenAI()


def ask_via_chat_completions(prompt):
    return client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )


def ask_via_messages_api(prompt):
    return client.messages.create(
        model="claude-3",
        messages=[{"role": "user", "content": prompt}],
    )


def ask_with_unpacked_kwargs(payload):
    return client.chat.completions.create(**payload)


def ask_through_wrapper(model, messages):
    return generate(model=model, messages=messages)


def ask_via_deeply_nested_chain(session):
    return session.inner.client.messages.create(
        model="claude-3",
        messages=[],
    )

"""Fixture: near-miss calls that must NOT be flagged as model calls."""

import openai

client = openai.OpenAI()


def list_models():
    # Attribute chain ends in .list, not .create; only one keyword present.
    return client.chat.completions.list(model="gpt-4")


def append_message(new_message):
    # Chain ends in .append, and the argument is positional, not a keyword.
    return client.messages.append(new_message)


def create_without_messages():
    # Bare name call, and only the "model" keyword is present.
    return create(model="gpt-4")


def build_config(history):
    # A dict literal is not a Call at all, even though the keys match.
    return {"model": "gpt-4", "messages": history}


def call_unrelated_client(payload):
    # "messages_client" is a single Name, not an attribute chain of
    # .messages.create; the argument is positional, not a keyword.
    return messages_client.create(payload)


def create(self, model, messages):
    # A function definition, not a call site; the dict body isn't a Call.
    return {"model": model, "messages": messages}


def log_call(model, messages):
    # "model=" and "messages=" appear only inside a string literal, not as
    # actual keyword arguments.
    return logger.info("model=%s messages=%s", model, messages)


def get_create_handler():
    # An Attribute reference to .chat.completions.create with no enclosing
    # Call at all.
    return client.chat.completions.create

"""Fixture: two model call sites sharing a single line, to pin sort order."""

import openai

client = openai.OpenAI()

client.messages.create(model="claude-3", messages=[]); client.chat.completions.create(model="gpt-4", messages=[])

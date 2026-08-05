# Project

Static analyzer for LLM agent cost architecture. Python, packaged to PyPI.

## Workflow

I do not review your code line by line. Tests and gates are the review.
Because of that: when a spec is ambiguous, ask instead of choosing.

Test first, always:

1. You write the failing test and show it to me.
2. I approve it.
3. You implement.

If implementation exists before I approved a test, delete it and restart.

@.claude/rules/testing.md
@.claude/rules/detectors.md

Release and packaging rules are in `.claude/rules/release.md`. Read it when
we are cutting a version, not before.

## Mine, not yours

- Committing and tagging.
- Changing any threshold in `.claude/rules/`.

# Testing gates

A task is done when all of these pass. Report the observed number for each.
Write NOT RUN for any gate you did not run in this session.

| Gate | Threshold | Command |
|---|---|---|
| Tests | 0 failed, 0 skipped | `pytest` |
| Line coverage | >= 90% on `src/` | `pytest --cov=src` |
| Branch coverage | >= 85% | `pytest --cov=src --cov-branch` |
| Mutation score | >= 80% on `src/arctoken/detectors/`, `src/arctoken/walker.py`, `src/arctoken/payloads.py`, `src/arctoken/project.py`, and `src/arctoken/callgraph.py` | `mutmut run` |
| Types | clean | `mypy --strict src/` |
| Lint | clean | `ruff check && ruff format --check` |

A skipped test counts as a failure. List surviving mutants individually with
file, line, and mutation; a count alone is not useful to me.

Mutation testing is scoped to `src/arctoken/detectors/`, `src/arctoken/walker.py`,
`src/arctoken/payloads.py`, `src/arctoken/project.py`, and
`src/arctoken/callgraph.py` deliberately. Do not widen it further.

Mutation testing does not run natively on Windows; mutmut requires WSL or Linux.
On Windows, report NOT RUN for that gate rather than omitting it or estimating a
score. The other five gates run everywhere.

## Not allowed

- Editing, deleting, or `xfail`-ing a test to make a gate pass. If you believe
  a test is wrong, stop and tell me why.
- `# pragma: no cover`, or `# type: ignore` without a reason on the same line.
- Mocking the unit under test. Mock only at process boundaries: filesystem,
  network, clock.

# Detector correctness

A false positive is worse than a missed detection. One wrong finding makes a
user distrust every other line of output. Optimize for precision.

Every detector needs fixtures on both sides before it is done:

- `tests/fixtures/dirty/` — code containing the anti-pattern. Must be flagged.
- `tests/fixtures/clean/` — code that looks similar but is correct. Must NOT
  be flagged.

Clean fixtures must include the near misses, not just obviously-fine code:

- `cache_control` set correctly on the stable prefix
- message history bounded by an explicit truncation or windowing call
- tool schemas built once outside the loop and reused
- a call inside a loop that is genuinely intended to run once per item

A detector with no clean fixtures is not done. A false positive found in real
code is a P0: write the clean fixture first, then fix.

## Cost arithmetic

Token-to-dollar math is asserted against values I hand-calculated and checked
into the test file as literals. Never assert against the implementation's own
output, and never regenerate those literals from code.

Pricing lives in one module. No rate constants anywhere else.

# Ideas

Out of scope for now. Recorded so they are not rediscovered from scratch.

## Self-reachable model calls are an unbounded cost multiplier

A function that is reachable from itself *through* a model call has no visible
bound on how many times it hits the API. A loop multiplies cost by the number
of iterations, which is at least finite and often inspectable; recursion around
a model call multiplies it by a depth that is decided at runtime, and a
mistaken base case bills the difference.

This is probably the highest-value finding the tool could produce, and the call
graph makes it cheap to detect: once transitive reachability exists, it is the
set of functions appearing in their own reachability path.

Not scoped yet. Worth its own cycle, including what to report when the
recursive edge is unresolved rather than certain.

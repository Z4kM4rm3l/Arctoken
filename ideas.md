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

## Callables passed by reference are invisible to edge extraction

Edges come from `Call` nodes, so a function handed to something else as a value
never produces one. `executor.map(ask, items)`, `functools.partial(ask)`, a
decorator, and callback registration all leave `ask` as a bare `Name`, and the
graph records nothing.

This is worse than an ordinary missed edge, because the shapes that pass a
callable by reference are usually the fan-out shapes: `executor.map(ask, items)`
is a model call per item, concurrently. The graph reports no edge at all, which
reads as "no fan-out here" rather than "could not tell".

A first pass could treat a bare `Name` argument that resolves to a project
function as a weaker kind of edge, kept apart from called edges so the
distinction stays visible.

## The report must surface unresolved edges with their loop context

`reaching` is the set of functions that *definitely* reach a model call.
Unresolved callees cannot be followed, so a function whose only route to the
API runs through one is absent from it — including when that call sits inside
a loop, which is precisely the shape worth worrying about.

That exclusion is correct in the graph and becomes a silent false negative the
moment the report treats `reaching` as the whole story. Unresolved edges have
to be reported next to it, carrying their loop context, so an unreadable call
repeated per item reads as "could not tell, and it is in a loop" rather than
as silence.

## A bulk outside-tree count should hint at scanning from a parent

Running the tool on a subpackage makes every relative import that climbs above
the scan root resolve as `outside-tree`. Each one is individually correct, but
in bulk they are a single fact about how the tool was invoked, not dozens of
separate findings.

The report layer should notice the concentration and say so directly: scanning
from the parent directory would resolve them. Left as a wall of unresolved
edges, the honest answer reads as the tool failing, which is the wrong first
impression to give and the one most users will form.

# Transcript contract

A Transcript is the Agent's normalized, traceable reading of one Job's Evidence.
It is not another raw source.

Save:

- ordered cues with `start_ms`, `end_ms`, and text;
- readable full text;
- every Evidence ID used;
- material corrections and their reasons;
- unresolved uncertainty;
- `quality.status=usable` or `verified`.

Do not mark `verified` merely because extraction completed. Check names,
numbers, negation, causal wording, quotes, and any passage that drives the
requested deliverable.

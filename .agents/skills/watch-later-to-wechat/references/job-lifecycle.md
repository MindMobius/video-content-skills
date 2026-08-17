# Job lifecycle

Stages move forward:

```text
queued -> inspecting -> evidence -> transcript -> content -> handoff -> completed
```

Statuses:

- `queued`: ready for the caller to advance;
- `running`: current stage is in progress;
- `retryable`: technical failure; retry within Profile limits;
- `paused_auth`: real browser login boundary;
- `unprocessable`: physical evidence or content cannot be made sufficient;
- `failed`: non-retryable implementation/integrity failure;
- `completed`: all requested and authorized stages are proven.

Do not move a stage backward. Resume `retryable` or `paused_auth` at its current
stage. `run_id` groups one scan's new Jobs; it does not merge their Evidence or
replace per-Job provenance.

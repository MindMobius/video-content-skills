# Audit Fidelity

Audit the current deliverable as if you did not author it. Use the content map
and relevant source ranges, not memory of the drafting process.

## Task

1. Enumerate every material statement a reader could take away.
2. Map it to one or more content-map claim IDs.
3. Classify it as `faithful`, `compressed_but_faithful`, `distorted`, or
   `unsupported`.
4. Check every required claim and caveat from the media plan for visible
   presence.
5. Check attribution, translation, certainty, causal language, numbers, names,
   and whether uncertainty was hidden by compression or design.
6. Check the declared narrative voice. For `source_author`, flag external
   wrappers such as “这个视频认为”; for `preserve_speakers`, flag collapsed or
   ambiguous speaker identities.
7. Check that the carrier has a coherent information architecture. A different
   order from the source is not an error unless it changes causality, sequence,
   qualification, or meaning.
8. Record concrete repair actions for every error.

## Status rule

- Use `pass` only when no semantic issue remains.
- Use `pass_with_warnings` only for limitations that do not change meaning.
- Use `fail` for unsupported statements, distortion, missing required context or
  caveats, hidden uncertainty, attribution errors, or translation errors.

A warning is not a softer label for an unresolved error. A failed deliverable
must be revised and saved as a new revision before another audit.

Return the JSON document required by
[`../../../../schemas/fidelity-audit.schema.json`](../../../../schemas/fidelity-audit.schema.json).

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
8. For a public adaptation, check the source and transformation disclosure
   separately from the body. A required disclosure must precede the argument;
   narrator language inside that disclosure does not excuse narrator wrappers
   inside a `source_author` body.
9. For a rendered article, check that renderer defaults did not introduce a
   fictional author, unsupported stance, stock CTA, or promotional promise. If
   local images remain, require visible relative-path markers, matching local
   files, an ordered import checklist, and an explicit preview-copy warning. In
   the default minimal-edit mode, each image marker must be one human-visible
   path line, may carry machine metadata such as `data-local-image-slot`, and
   must require deletion of at most one visible element. Flag boxed placeholder
   cards, duplicated descriptions, repeated instructions, or absolute machine
   paths unless the user explicitly authorized a descriptive slot.
10. Audit the clean portable deliverable before any downstream platform
    handoff. A successful clipboard paste or WeChat image upload cannot repair
    a missing marker, unsupported statement, or stale audit, and must not be
    used to change this audit status.
11. Record concrete repair actions for every error.

## Status rule

- Use `pass` only when no semantic issue remains.
- Use `pass_with_warnings` only for limitations that do not change meaning.
- Use `fail` for unsupported statements, distortion, missing required context or
  caveats, hidden uncertainty, attribution errors, or translation errors.

A warning is not a softer label for an unresolved error. A failed deliverable
must be revised and saved as a new revision before another audit.

A correctly disclosed manual image step can be a warning because the package is
still truthful and usable. A missing required cover/disclosure, hidden local
image dependency, false “ready to paste” claim, absolute machine path, or a
renderer placeholder that violates the selected minimal-edit contract is a
blocker. Keep this package-level status unchanged if an optional downstream
Skill later imports the images into a signed-in editor; platform state is a
separate receipt, not fidelity evidence.

Return the JSON document required by
[`../../../../schemas/fidelity-audit.schema.json`](../../../../schemas/fidelity-audit.schema.json).

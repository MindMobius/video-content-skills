# Content Engineering Contracts

## Schemas

- [`content-project.schema.json`](../../../../schemas/content-project.schema.json):
  pinned evidence snapshot, lifecycle, and artifact registry.
- [`content-map.schema.json`](../../../../schemas/content-map.schema.json):
  medium-independent semantic reconstruction.
- [`media-plan.schema.json`](../../../../schemas/media-plan.schema.json): selected
  carrier, user selection authority, required elements, omissions,
  carrier-specific restructuring, narrative voice, structure, and rendering
  contract.
- [`fidelity-audit.schema.json`](../../../../schemas/fidelity-audit.schema.json):
  statement-level review and delivery gate.

## Versioning

The source subtitle manifest and evidence files are never copied into or changed
by the content project. Their hashes are pinned at initialization. A changed
manifest or evidence file makes the project invalid and requires a new project.

Content maps, media plans, deliverables, and audits are derived artifacts. Every
save creates a numbered revision. Saving a new content map invalidates the
current media plan, deliverable, and audit. Saving a new media plan invalidates
the current deliverable and audit. Saving a new deliverable invalidates the
current audit.

## IDs

- Evidence IDs such as `ev-0001` come from the subtitle manifest catalog.
- Evidence reference IDs use `evref-0001`.
- Claim IDs use `claim-0001`.
- Caveat IDs use `caveat-0001`.
- Saved artifacts use `cmap-001`, `mplan-001`, `dlv-001`, and `audit-001`.

IDs are local to one content project. They are stable across downstream
artifacts and allow a deliverable statement to be traced back to exact subtitle
ranges.

## Structural versus semantic validation

Tools enforce schemas, known IDs, source/artifact hashes, current-revision
relationships, required-element coverage, and audit bookkeeping. The Agent is
responsible for whether a paraphrase is faithful, a source truly supports a
claim, a caveat is consequential, a narrative voice matches the source, and a
medium-specific information architecture is appropriate. Tools validate the
declared strategy and references; they do not algorithmically rewrite content.

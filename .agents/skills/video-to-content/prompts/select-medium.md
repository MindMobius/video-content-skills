# Decide the Medium with the User

Use this reasoning frame to analyze viable carriers from the current content
map. Author `video-content/media-plan-v1` only after the user has selected a
carrier or explicitly delegated the decision.

## Task

Identify the smallest carrier that preserves the source's essential reasoning.
Do not recommend by popularity or presumed algorithmic performance.

Evaluate:

- argument depth: how many dependent steps must remain connected;
- context dependency: how much setup is needed before a conclusion is safe;
- visual potential: whether hierarchy, comparison, sequence, or causality is
  genuinely easier to understand visually;
- uncertainty level: how much qualification or unresolved evidence must remain
  visible;
- audience state: what the user actually knows, not a fabricated persona;
- communication goal: orientation, understanding, reference, recall, or spoken
  delivery.

## Routing heuristics

- Prefer an article when removing connective reasoning would change the claim.
- Prefer one page when one hierarchy, comparison, process, or causal chain can
  carry the core without tiny text or hidden caveats.
- Prefer cards when ideas are modular but their order still matters.
- Prefer a brief when only orientation is required and the omitted details are
  explicitly declared.
- Prefer a script when oral rhythm, examples, or transitions are part of the
  intended experience.

## Decision gate

- If the user named a carrier, use it unless it would materially distort the
  content; ask before substituting another carrier.
- If the user explicitly asked the Agent to choose, select one carrier and
  record why.
- Otherwise present a concise recommendation and its main tradeoff, then stop.
  Do not create a media plan or deliverable until the user decides.
- If the user wants only the organized subtitle, return to the subtitle
  deliverable and end the transformation workflow.

## Quality gate

Mark every core claim and consequential caveat as required. Record other claims
as deliberate omissions with reasons. Describe at least one rejected alternative
so the decision can be reviewed. The plan records one user-authorized primary
deliverable. Set `selection_authority=user_selected` when the user named the
carrier, or `selection_authority=user_delegated` when the user explicitly asked
the Agent to choose.

Declare an `adaptation_strategy` for that carrier. Prefer
`reconstructed_for_medium`: state how the Agent will merge, split, reorder, or
reframe material so the result works as that carrier. Use
`preserve_source_order` only when the original sequence is itself meaningful,
such as a procedure, chronology, or narrative reveal.

For a video-derived `article`, visual directions default to the original cover
and timestamped frames from the source video. Record useful source moments in
`structure[].visual_direction` instead of inventing a diagram from the article's
conceptual structure. Selecting `article` does not authorize generated diagrams,
AI illustrations, stock images, or synthetic visual summaries. Put such a
visual in the plan only when the user explicitly requested it or separately
approved that visual choice. If no source frame materially helps a section,
plan fewer images rather than filler.

Declare `narrative_voice` separately from factual attribution:

- single-author or joint-author monologue: default to `source_author` and bind
  the source speaker IDs that form the collective author voice;
- interview or multi-speaker discussion: use `preserve_speakers` and retain
  distinct identities;
- use `editorial` only when the user wants a separate editor or curator voice.

For source-author voice, list any external wrappers that would break the voice,
such as “这个视频认为” and “作者表示”. Attribution remains in the content map
even when the visible artifact speaks directly as the author.

Return the JSON document required by
[`../../../../schemas/media-plan.schema.json`](../../../../schemas/media-plan.schema.json).

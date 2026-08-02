# Create Deliverable

Use the current content map and media plan as the semantic and presentation
contracts.

## Task

Create only the selected medium. Follow the media plan's adaptation strategy;
do not mirror transcript segments or playback order by default. You may merge,
split, compress, reorder, foreground, paraphrase, or translate material, but
you may not strengthen certainty, erase attribution, invent causality, remove a
consequential caveat, or turn an Agent inference into the speaker's statement.

Follow the declared narrative voice. With `source_author`, write as the author
would address the audience directly, using first-person or an unwrapped direct
voice. Do not say “这个视频认为”, “视频里提到”, “作者表示”, or otherwise place an
external narrator between author and reader. This changes presentation, not
provenance: claim IDs and speaker attribution remain unchanged in metadata.

With `preserve_speakers`, keep each speaker distinguishable. Do not collapse an
interview into a fictional single-author voice.

Carrier-specific guidance:

- Article: preserve the reasoning chain and use headings to expose structure.
- One page: use one visual grammar; reduce the number of claims before reducing
  legibility; build a scan-friendly hierarchy rather than a miniature timeline;
  keep qualifications adjacent to the claims they constrain.
- Card series: one semantic job per card, with a visible sequence and no false
  cliff-hangers.
- Brief: lead with the answer, then evidence, limits, and where to inspect more.
- Script: write for speech while retaining attribution and logical transitions.

## Output handoff

Alongside the artifact, prepare:

- `used_claim_ids`: every claim represented, including paraphrases;
- `used_caveat_ids`: every caveat represented;
- the actual serialization format and title.

Do not count a claim as represented merely because it appears in hidden metadata.
The human-visible artifact must carry it.

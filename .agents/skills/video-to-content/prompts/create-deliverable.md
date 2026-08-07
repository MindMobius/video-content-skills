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

When the requested deliverable is intended for public distribution and the
user's instructions require source disclosure, place a visually separate
attribution block before the body:

- use the original cover when it is available and authorized for this use;
- name the source creator, source title, and canonical source URL;
- state that the artifact was transcribed, compressed, reorganized, translated,
  or otherwise adapted when applicable;
- disclose that those transformations can introduce deviations and direct the
  reader back to the original source.

This block belongs to the deliverable; creating it does not authorize upload or
publication. It is not an editorial narrator wrapping the body, so it does not
violate `source_author` voice. Keep it outside the author's argument. Do not use
a disclaimer to hide unsupported additions, transfer all factual responsibility
to the source, or imply the creator endorsed the adaptation.

Carrier-specific guidance:

- Article: preserve the reasoning chain and use headings to expose structure.
- One page: use one visual grammar; reduce the number of claims before reducing
  legibility; build a scan-friendly hierarchy rather than a miniature timeline;
  keep qualifications adjacent to the claims they constrain.
- Card series: one semantic job per card, with a visible sequence and no false
  cliff-hangers.
- Brief: lead with the answer, then evidence, limits, and where to inspect more.
- Script: write for speech while retaining attribution and logical transitions.

For a WeChat Official Account article or an equivalent copy-oriented rich-text
handoff, read
[`../references/wechat-article.md`](../references/wechat-article.md) before
drafting. Build and stabilize the article manuscript before styling it. An
optional renderer can choose typography and markup, but its sample copy,
signature, CTA, and author placeholders are not source content and must not be
introduced without user authorization.

### Local image handoff for paste-oriented HTML

When an article is meant to be copied into a rich-text editor and an image is
only available as a local file, keep the image local and leave a human-visible
insertion slot in the HTML. The slot must name the file and describe the image
that belongs there. Place the local files beside the deliverable or in a clearly
named assets directory, and provide a short import checklist in article order.

Do not leave a relative path, `file:` URL, `data:` URL, or `blob:` URL in an
`img` element and call the artifact directly pasteable. A local browser may
render that reference, but copying rich HTML does not reliably transfer the
image bytes into the target editor. Renderer documentation does not override
this handoff rule.

Uploading images, rewriting them to a platform CDN, or inserting them into a
platform editor is a separate publishing integration and remains outside this
project. The deliverable should make the manual boundary obvious rather than
hide it behind a successful copy message.

If the deliverable includes a browser preview with a copy button, its label and
success message must say that only the formatted body was copied and that local
images still need manual insertion. Never show an unqualified "ready to paste"
message while local image slots remain.

Save the clean body artifact as the deliverable. A browser preview wrapper,
copy-button script, local image binary, and import checklist are package
companions, not substitutes for the audited human-visible article.

## Output handoff

Alongside the artifact, prepare:

- `used_claim_ids`: every claim represented, including paraphrases;
- `used_caveat_ids`: every caveat represented;
- the actual serialization format and title.

Do not count a claim as represented merely because it appears in hidden metadata.
The human-visible artifact must carry it.

Stop after producing and auditing the artifact. Uploading, saving to a platform
draft box, scheduling, publishing, and account management are outside this
project's contract.

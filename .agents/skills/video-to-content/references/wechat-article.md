# WeChat Article Delivery

Read this reference only when the selected medium is `article` and the requested
handoff is a WeChat Official Account article or another rich-text editor with
the same copy-and-paste constraints.

This is a delivery protocol, not a writing template. The content map, media
plan, source evidence, and user instructions remain authoritative. A renderer
may decide typography and component markup; it may not decide what the source
means, add an editorial stance, or turn the article into marketing copy.

## Responsibility split

- `video-to-content` owns semantic reconstruction, source attribution,
  narrative voice, public disclosure, deliberate omissions, and fidelity.
- An optional renderer Skill owns theme selection, rich-text-safe markup,
  preview generation, and renderer-specific HTML validation.
- The optional `wechat-draft-handoff` Skill may place an already audited package
  into an already signed-in editor after explicit user authorization. It owns
  transient clipboard assembly, image-ingestion verification, only the
  specifically authorized draft save, and a validated live-state receipt.
- The user owns the communication objective and any account signature, CTA,
  originality declaration, or promotional framing.
- The portable package owns a complete manual fallback for local-image import.
- The Python/MCP content project stops before platform state. Scheduling,
  publishing, mass sending, monetization, and account management remain outside this project.

Renderer defaults never override the media plan or user preferences. Omit a
stock author signature, follow prompt, QR-code block, “点赞 / 在看 / 转发” CTA,
or other account-growth shell unless the source already contains it or the user
explicitly requests it. Do not invent the source creator's endorsement or use
the renderer's sample author as the article author.

## Build the manuscript first

Create the semantic article before styling it. The article may merge, split,
reorder, or foreground source material to suit reading; it should not mirror
the playback timeline. For `source_author`, the body speaks directly in the
source author's voice. Do not add “这个视频认为”, “原视频称”, “视频里提到”, or
similar narrator wrappers.

For a public adaptation whose media plan requires attribution, use this order:

1. a visible slot for the original cover when it is a local asset;
2. a visually separate source and transformation disclosure block;
3. the reconstructed article body.

The disclosure names the source creator, original title, and canonical URL. It
also states the actual transformations and any material uncertainty, including
whether external facts were checked. This disclosure is provenance metadata,
not part of the source author's argument. Scan the body separately from the
disclosure when checking narrator wrappers.

Keep a Markdown manuscript such as `article.md` in the delivery package. It is
the canonical manuscript for that deliverable revision; the content map and
media plan remain the semantic and provenance contracts. The rich-text HTML is
a rendered derivative, not a replacement for either layer.

## Use a renderer as an optional downstream Skill

If an appropriate renderer Skill is installed or discoverable, read its
instructions and use it after the manuscript is stable. The tested integration
is [`isjiamu/gzh-design-skill`](https://github.com/isjiamu/gzh-design-skill), but
it is not a dependency of this repository and other renderers may be used.

A standard Skill installer can inspect that repository without installing it:

```powershell
npx -y skills@1.5.22 add isjiamu/gzh-design-skill --list
```

It should report the `gzh-design` Skill. If it is absent and rich-text styling
is required, inspect the third-party source, then install `gzh-design` in the
caller's user-level or isolated Skill scope according to that Agent's policy.
Do not copy it into this repository or add it to the core Python requirements.
If no renderer is available, deliver the stable manuscript and use only markup
the calling Agent can validate; do not block semantic content work on a theme.

When using `gzh-design-skill`:

- select a registered theme from the content's tone and density rather than
  copying a theme from an unrelated example;
- treat its component library as presentation guidance and remove stock
  signature or CTA components when they conflict with the objective;
- produce a clean `<section>...</section>` body fragment with inline styles,
  then run its `scripts/validate_gzh_html.py` until both errors and warnings are
  zero;
- override a generic boxed material-placeholder component when local images use
  the minimal-edit handoff below; renderer defaults do not authorize extra
  cleanup work for the human editor;
- create the browser preview with its `scripts/wrap_preview.py`, but do not save
  the preview shell as the content deliverable.

On Windows PowerShell, set UTF-8 before running renderer scripts that print
Unicode symbols:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python <gzh-skill-root>\scripts\validate_gzh_html.py <clean-html>
python <gzh-skill-root>\scripts\wrap_preview.py <clean-html>
```

Renderer validation proves markup compatibility, not semantic fidelity. A
beautiful page with unsupported claims still fails the content audit.

## Package local images explicitly

A reusable handoff package should contain the smallest useful set of artifacts:

```text
wechat-article/
├─ article.md
├─ article.html
├─ article-preview.html
├─ cover.jpg                    # or assets/<descriptive-name>.<ext>
└─ image-import-checklist.md
```

Names may be localized, but their roles must remain obvious. Optional desktop
or mobile QA screenshots may be included as inspection evidence; they are not
part of the article body.

For every local image, default to minimal-edit mode:

1. keep the binary file in the package;
2. put one human-visible line containing the relative asset path at the exact
   article position, for example `assets/01-mission.jpg`;
3. create any desired vertical space with margins on that same element;
4. when the HTML format permits it, attach `data-local-image-slot` with the same
   relative path for machine validation;
5. list the same relative path in article order in
   `image-import-checklist.md`;
6. do not leave a relative, `file:`, `data:`, or `blob:` source in an `img`
   element, and do not expose an absolute machine path.

The human-visible marker should contain only the path. Do not add a border,
background, icon, image title, repeated description, or a second deletion
instruction. After manual insertion, the editor should delete at most one
visible element: the path line itself. Machine-facing traceability belongs in
attributes and validation, not in extra article UI.

A descriptive slot is opt-in. Use it only when the user explicitly requests
editor guidance or the filename is genuinely ambiguous. The checklist should
state once that copied rich text does not contain local image bytes, then list
relative paths in article order. Add a short description only where it resolves
real ambiguity; do not repeat insertion and deletion instructions for every
image. Do not upload an image to invent a transferable URL.

If the preview has a copy button, use qualified wording such as “复制排版正文”.
The success message must say that the formatted body was copied and local
images still require manual insertion. The preview may render the same minimal
path lines; it must not claim that an incomplete package is “ready to paste”.

## Optional signed-in draft handoff

The clean package above remains the canonical and portable boundary. Only after
it has a current fidelity audit and `ready_for_delivery=true`, and only when the
user explicitly asks for platform handoff, finish `video-to-content` and read
[`../../wechat-draft-handoff/SKILL.md`](../../wechat-draft-handoff/SKILL.md).

That downstream Skill may replace the path markers in a one-time clipboard
payload with correctly typed Base64 `data:` images. The payload exists only in
memory or the clipboard long enough to paste the whole article once. It must not
be saved as `article.html`, committed, logged, or treated as a new deliverable.
The signed-in WeChat editor can then upload the images and rewrite their sources
to its own CDN.

A successful handoff requires live verification that the intended image count
is visible, all images have WeChat-hosted sources, no transient or local sources
remain, metadata is correct, and the explicitly authorized draft save completed.
If rich clipboard image transport is unavailable or verification fails, return
to the path-marker package and report the exact manual insertion step. Platform
success never changes the content fidelity audit.

Start an external `wechat_handoff` content phase before the first editor
mutation, and finish it only after save plus saved-page read-back. For a saved
draft, persist `wechat-draft-receipt.json` beside the article package using
`video-content/wechat-draft-receipt-v1`, then validate it against the current
content project:

```powershell
python scripts/validate_wechat_draft_receipt.py `
  <wechat-article-directory>\wechat-draft-receipt.json `
  --project <content-project>\project.json
```

The receipt is an observation of platform state, not a new deliverable. It must
bind the current project, deliverable, and fidelity audit; record stable
`appmsgid`, image and metadata read-back, durable manual-save history, and the
measured handoff timestamps; and state `published=false` with an empty
`publish_actions_performed` array. Do not persist URL tokens, credentials,
clipboard Base64, or hidden browser state. Require validator `valid=true` before
reporting a saved-draft success.

## Validate two independent layers

Before saving the final deliverable, validate both layers:

### Content and provenance

- all required claim and caveat IDs are visibly represented;
- the body follows the declared narrative voice;
- the cover slot and disclosure precede the body when required;
- the disclosure states the real transformation and verification boundary;
- renderer defaults did not add a new author identity, stance, CTA, or
  promotional promise;
- title, headings, and highlighted text do not strengthen the source claim.

### Rendering and handoff

- the clean HTML passes the chosen renderer's deterministic validator;
- the clean HTML contains no document or preview shell when the renderer
  requires a body fragment;
- local image path markers, local files, and checklist entries match one-to-one
  and in article order;
- default markers use one visible relative-path line per image, expose no
  absolute machine path, and require deletion of at most one visible element;
- no local image is hidden behind an `img` reference that cannot survive copy
  and paste;
- the preview copy message describes the manual image boundary;
- when browser inspection is available, check both a desktop width and a narrow
  mobile width for overflow, illegible text, broken hierarchy, and accidental
  empty space.
- when signed-in draft handoff was explicitly requested, validate the separate
  `wechat-draft-receipt.json` against the current project after live save and
  read-back; do not fold platform state into the fidelity audit.

When this repository is available, run the dependency-free package validator
from the repository root before the final fidelity audit:

```powershell
python scripts/validate_wechat_package.py <wechat-article-directory>
```

Its `valid=true` result confirms the deterministic handoff contract: marker,
checklist, and local-file order; clean versus preview HTML boundaries; absence of
persisted Base64, local URI schemes, absolute paths, underline emphasis, and
stock renderer shells; and qualified preview copy wording. It does not decide
whether the article's claims, voice, or caveats are faithful.

Save the clean human-visible article HTML with
`save_video_content_deliverable`; do not save the preview wrapper. Perform a
fresh fidelity audit against that saved revision, then call
`validate_video_content_project`.

A package with disclosed external-verification limits or a correctly declared
manual image step may use `pass_with_warnings` if no semantic error remains. A
missing required disclosure, hidden uncertainty, unsupported statement, wrong
voice, or absent local-image handoff is a blocker and must be repaired before
delivery.

## Final handoff

Report the clean HTML, preview, manuscript, local assets, and import checklist
as separate files. By default, state the one remaining human action precisely:
paste the formatted body, import each local image at its path line, and delete
that one line.

If the user separately requested signed-in draft handoff, complete and report
the audited content artifact first, then route to `wechat-draft-handoff`. Report
the validated receipt path, project/deliverable/audit IDs, visible loaded and
WeChat-hosted image counts, stable `appmsgid`, durable save evidence, measured
`wechat_handoff` duration, warnings, and the explicit fact that nothing was
published. Do not continue from a saved draft into scheduling or publishing.

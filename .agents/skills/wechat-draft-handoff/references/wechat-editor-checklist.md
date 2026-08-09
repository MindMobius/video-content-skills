# WeChat Editor Checklist

Use this checklist as a state machine, not as a coordinate script. Control names
and layout may change; the observable preconditions and postconditions do not.

## A. Authorization and input

- [ ] The user explicitly requested editor handoff.
- [ ] Saving the draft is explicitly in scope.
- [ ] The exact audited deliverable and its local asset directory are known.
- [ ] `ready_for_delivery=true` and the current fidelity audit was read.
- [ ] Title, summary source, cover instruction, author field, and originality
      setting are known or intentionally unchanged.

## B. Package preflight

- [ ] The source is the clean body HTML, not the preview wrapper.
- [ ] Local-image markers and files match one-to-one and in article order.
- [ ] The clean HTML contains no persisted Base64 image payload.
- [ ] No absolute local path will enter the editor or final report.
- [ ] The original source and transformation disclosure remains before the body
      when required.

## C. Live editor preflight

- [ ] The visible page is the intended signed-in WeChat article editor.
- [ ] Login is active; no credential or cookie extraction is needed.
- [ ] Existing body content is blank or explicitly in scope for replacement.
- [ ] No unsaved unrelated draft will be destroyed.
- [ ] State is read from visible, enabled controls; hidden duplicate fields,
      inactive menus, and helper nodes are not treated as the current value.

## D. Clipboard transport and paste

- [ ] Each marker was replaced only in the temporary payload with a correctly
      typed `data:image/...;base64,...` image.
- [ ] The temporary payload was not written to the delivery package or logs.
- [ ] The complete article was pasted once in the intended order.
- [ ] WeChat was given time to upload and rewrite all images.

## E. Ingestion verification

- [ ] Visible, non-empty, successfully loaded body-image count equals the
      intended image count; hidden, zero-size, empty-source, and helper image
      nodes are excluded.
- [ ] Every counted image resolves to a WeChat-hosted source, typically
      `mmbiz.qpic.cn`.
- [ ] `data:`, `file:`, `blob:`, and `assets/...` image sources are absent from
      the live editor after upload.
- [ ] No local path markers remain unless manual fallback is intentional.
- [ ] Text, disclosure, hierarchy, and restrained styling survived the paste.
- [ ] Image and field checks use the current rendered state rather than the
      first matching DOM node or the total number of `img` elements.

## F. Metadata and save

- [ ] Title matches the authorized audited title or user revision.
- [ ] Summary contains no claim absent from the audited article.
- [ ] “从正文选择” used the designated body image; crop confirmation completed,
      the visible cover preview is WeChat-hosted, and the empty-cover placeholder
      is gone.
- [ ] Visible author and originality controls were read directly and were not
      inferred from hidden duplicates.
- [ ] Draft save produced a durable receipt: preferably a stable article ID and
      a persisted manual-save or version-history entry when both are available.
- [ ] After saving, title, summary, body, imported images, and cover were read
      back and remained complete.
- [ ] No publish, schedule, mass-send, originality, or account control was used.

## G. Receipt

Report title, intended/imported visible image counts, cover, summary, the durable
save receipt, warnings, and the explicit fact that nothing was published. If any
checkbox in sections E or F is unresolved, report a partial handoff and the
exact manual action instead of declaring completion.

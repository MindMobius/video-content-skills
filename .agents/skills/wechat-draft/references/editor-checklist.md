# Visible editor checklist

Before mutation:

- exactly one visible body editor;
- current page is the intended draft editor;
- user/automation authorization includes saving a draft;
- no existing Draft Receipt for a new draft; for an authorized revision, exactly one current validated Receipt and its numeric `appmsgid`;
- exactly one transport selected: validated `article-import.docx` for image-rich content when available, otherwise transient rich HTML;
- for DOCX, the file matches the final Content, embeds each intended body image once in block order, and lives under the current Job handoff package;
- every DOCX image comes from the final Content Artifact, not a scout preview; its pixel aspect ratio matches the document display extent, with maximum width allowed but no forced height;

After document conversion or body placement:

- actual opening, middle, and ending inspected; an import-complete signal alone is insufficient;
- exact approved title; reject an import-derived placeholder such as `article-import`;
- all intended real images visible, complete, non-zero size, and WeChat-hosted; exclude zero-size editor separators;
- each image reports positive natural width/height and displayed width/height, with the same aspect ratio;
- zero relative-path markers in the body;
- source disclosure and ending still present;
- no stock follow/QR/engagement shell introduced;
- summary filled and original-video cover selected;
- author/originality untouched unless explicitly authorized;
- when required, Browser Adapter reports exactly one visible selected creation-source control for **“内容由AI生成”**.

After save:

- stable numeric `appmsgid`;
- durable manual-save/history evidence;
- refresh/reopen the same draft;
- take a fresh Browser Adapter v3 snapshot; title, body, image count, image aspect ratios, cover, summary, and required AI creation-source declaration still match;
- set `creation_source.read_back=true` only from this post-refresh snapshot, never from the earlier click or save toast;
- a revision still has the exact previous numeric `appmsgid`;
- observation contains no raw URLs, tokens, storage, cookies, or clipboard HTML.

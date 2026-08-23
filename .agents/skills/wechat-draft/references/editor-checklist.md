# Visible editor checklist

Before mutation:

- exactly one visible body editor;
- current page is the intended draft editor;
- user/automation authorization includes saving a draft;
- no existing Draft Receipt for a new draft; for an authorized revision, exactly one current validated Receipt and its numeric `appmsgid`;

After body placement:

- exact approved title;
- all intended images visible, complete, non-zero size, and WeChat-hosted;
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
- take a fresh Browser Adapter snapshot; title, body, image count, cover, summary, and required AI creation-source declaration still match;
- set `creation_source.read_back=true` only from this post-refresh snapshot, never from the earlier click or save toast;
- a revision still has the exact previous numeric `appmsgid`;
- observation contains no raw URLs, tokens, storage, cookies, or clipboard HTML.

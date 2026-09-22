# Visible editor checklist

Before mutation (after the gate in [guarded-handoff.md](guarded-handoff.md)):

- exactly one visible body editor;
- current page is the intended draft editor;
- user/automation authorization includes saving a draft;
- no existing Draft Receipt for a new draft; for an authorized revision, exactly one current validated Receipt and its numeric `appmsgid`;
- canonical `article-import.docx` from `wechat_prepare`, not a historical file or trial variant;
- a fresh `wechat_step` single-action permit before upload/save; the live account, tab and document identity match the checkpoint;
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
- summary filled and original-video cover selected; the selected cover preview is
  visible and non-zero, not merely a hidden `.js_cover_preview_new` element with a
  CSS `background-image`;
- author/originality untouched unless explicitly authorized;
- when required, Browser Adapter reports exactly one visible selected creation-source control for **“内容由AI生成”**.

After save:

- stable numeric `appmsgid`;
- durable manual-save/history evidence;
- refresh/reopen the same draft;
- take a fresh Browser Adapter v4 snapshot; title, body, image count, image aspect ratios, visible non-zero cover preview, summary, and required AI creation-source declaration still match;
- use a separate read-only draft-list view without navigating the editor away, and read the same numeric `appmsgid`; its card must have a visible thumbnail plus persistent cover-media fields and non-empty crop data;
- pass the fresh snapshot to `wechat_step readback`; use its generated Observation, never hand-fill `creation_source.read_back=true` from an earlier click or save toast;
- a revision still has the exact previous numeric `appmsgid`;
- observation contains no raw URLs, tokens, storage, cookies, or clipboard HTML.

## 实测过的编辑器操作要点（2026-09-23）

- 正文可能有两个 `.ProseMirror`：`.title-editor__input` 是标题，`#ueditor_0 .ProseMirror`
  （或 `.mock-iframe-body .ProseMirror`）才是正文；采集器必须区分，账号在编辑器页是
  `.appmsg_account_name`，`#title` 是隐藏后备字段。
- 标题输入：用可信点击（CDP）聚焦标题编辑器后直接 `execCommand insertText`；
  **禁止 `execCommand selectAll`**——它会越过编辑器边界选中正文，一次插入就能毁掉整篇正文。
  一旦发生，聚焦正文 Ctrl+Z 可恢复，然后不用 selectAll 重试。
- DOCX 官方导入的图片不注册为"正文图片"，封面弹层的"从正文选择"会报无可用图；
  走"从图片库选择"，用正文首图的 mmbiz URL 在缩略图中精确匹配。封面弹层需要先
  hover 再点击才展开。
- DataTransfer 合成粘贴（ClipboardEvent(paste, {clipboardData})）会被 ueditor 接受并
  触发图片上传管线；拖拽 File 的合成 DragEvent 不会被上传组件接受。
- 图片上传后正文会残留 display:none、0 尺寸的占位 img，采集器必须过滤零尺寸节点
  （与 Observation v4 的"零尺寸编辑器分隔节点不计入正文图"一致）。

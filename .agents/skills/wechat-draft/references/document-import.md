# 微信文档导入交付

## 唯一生成器

`wechat_prepare` 使用 `video_content.wechat_docx`，从已经审计的同一 Content 生成
`work/<content_id>/handoff-package/document-import/article-import.docx`。
正文文字、列表、引用、标题、图注和图片顺序都由 Content 决定；来源声明集中保留一处。
所有内嵌图使用 Content Artifact 原字节，`wp:extent` 保留像素画幅，仅限制宽度、高度按比例缩放。
程序重开 DOCX 检查全文、内嵌图 SHA-256/顺序和画幅，再输出传输摘要。

不再复制历史 `build_docx.py`，不提供 `--skip`、`--limit-images` 或重复图片的生产选项。
“某份 5 图文档成功”不等于微信有“5 PNG 限制”。单张图、图片数量、总体积与编辑器状态必须
分别验证，实验必须确认读到本次文件而不是上一次正文。未证实的猜想不得写成平台限制。

当前生成器输出的是带有标准 Word 部件（core/app properties、styles、settings、webSettings、
fontTable、numbering、theme）的 `standard-ooxml` 候选包，而不是只有 `document.xml` 和图片的
最小 ZIP。这样做是为了把“过度精简的 OOXML 可能不被微信转换器接受”变成一个可重复的对照实验；
它仍然不是微信后台兼容性的证明。若同一目标的两次导入都明确失败，保留该 DOCX、响应和页面
快照，不要修改正文来迎合导入器，按受控备用传输继续。

DOCX 是运输载体，不是第七种业务产物。既有文件字节不符时保留现场并报错，不静默覆盖。
当前失败的导入也不构成修改 Content、减少图片或省略细节的编辑理由。

## 导入前后

1. 先读 [guarded-handoff.md](guarded-handoff.md)，prepare/attach 后用新快照调用
   `begin_import`；获单次许可后，只上传其 `upload_path`，不上传历史副本或测试变体。
2. 等待导入完成，然后用 `verify_import` 检查完整正文指纹、全部图数量/顺序与天然/显示画幅。
   “正文长度 > 100”、任何弹窗、上传返回成功、文件名或上一次导入标题都不算成功。
3. Agent 仍检查正文开头、中部、结尾与图片语义位置。数据一致不替代来源忠实性审校。
4. 文件名生成的 `article-import` 不是文章标题；主动设置批准的标题和摘要、选择原视频封面并确认
   裁剪，作者留空、原创不选，按 Profile 选择“内容由AI生成”。
5. 由 `begin_save` 获单次保存许可，之后 `saved → 刷新 → readback → bind`。
   Observation v4 的图片、封面、声明要求不因导入成功而省略。

## 能力失败与回退

`setFiles: Not allowed` 是控制器文件选择能力不足，不是文件路径不对。不要复制/改名 DOCX 碰运气。
先观察并保留同一目标；未锁定目标前可以选择同一已登录会话中实际可控的编辑器。
锁定后按恢复协议处理；已知保存 ID 可用 `recover_saved` 切到可控标签页读取同一草稿，
未保存且身份未知时禁止通过新建来绕过。

低层剪贴板工具保留用于诊断，但当前受控路线不自动切换到剪贴板；
`wechat_prepare(copy_to_clipboard=true)` 会拒绝，防止把两条不同传输混进同一个未决编辑器。
后续若启用新的生产传输，必须同样绑定全文/图片指纹、检查点和恢复测试，不能只是改一行 Skill。

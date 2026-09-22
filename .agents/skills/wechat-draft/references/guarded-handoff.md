# 微信交接唯一执行入口

唯一顺序：`wechat_prepare → wechat_step → wechat_bind`。

此页是操作协议；判断逻辑在 `video_content.wechat_handoff`，不要另写一套。
Python API、CLI、MCP 调用同一服务。CLI 的成功值在 JSON `result` 内。
每次命令都沿用当前 config/home；示例中的 `python` 指项目解释器。

## 1. 准备或恢复

```text
python -m video_content.cli --config <config> --home <home> wechat prepare <job_id> <content_id> --authorized --save-draft --account-name <预期公众号名称>
```

账号名称来自用户当前授权或已确认的 `Profile.settings.wechat_account_name`。配置了该字段时可省略 `--account-name`，不同的显式账号会被拒绝；不能从“URL 有 token”推定账号正确。
修订已有草稿另加 `--replace-existing-draft`。返回：

- `document_import.path`：唯一待上传 DOCX，附 SHA-256、完整正文指纹和有序图片清单；
- `checkpoint.revision`：下一次步骤必须携带的版本号；过期版本会被拒绝；
- `checkpoint.phase / next_action`：从哪里恢复；
- `draft_target`：创建、原位修订或 `resume_pending`；
- `mutation_permitted=false`：prepare 本身不授权上传或点击保存。

仅全新 `prepared` 状态可以寻找/打开空白编辑器；已有正文、未决导入或未决保存必须恢复原目标。
以前已处于 handoff、却没有 checkpoint 的 Job 进入 `recovery_required`。先查原编辑器和草稿列表，
不能以“没有 Receipt”为依据判断从未保存。程序不会自动重置或删除这类状态。

## 2. 快照来自真实页面，不手填通过项

将 `scripts/browser-adapter.js` 中的 `collectHandoffSnapshot(options)` 在当前页面的
受支持 evaluate 上下文中执行。这个函数只观察，不点击、不导航、不上传。

`options` 至少提供：

- 从控制器当前标签页清单取得的 `browserId`、`tabId`；不要使用 session 别名冒充实际标签页 ID；
- 当前已检查的 `accountSelector`、`bodySelector`、`originalSelector`、`importBusySelector`；
- 若 Profile 要求 AI 声明，提供 `creationSourceSelector`；
- 从可见封面选择/裁剪确认动作取得的 `cropConfirmed`；
- 回读时，在另一个只读列表视图核对的 `draftListAppmsgid`、`draftListCover`。
  列表封面证据用现有 `summarizeDraftListCover`，不可只按标题猜测或导航掉编辑器。

函数产生 `snapshot_id`、`observed_at`、document identity、完整 `body_text`、可见图片尺寸、
对话框、加载状态与元数据。不要从旧快照复制；60 秒以上快照过期，已消费快照不能重用。
隐藏/缺失/多个同名控件不能记成通过。不要在 Observation 中保留 token、cookie 或 CDN URL。
快照文件仅放当前 Job/work 或 run 目录；交接 checkpoint 只保留正文哈希，不保留正文或浏览器 URL。

## 3. 每一步先检查，再执行获准动作

```text
python -m video_content.cli --config <config> --home <home> wechat step <job_id> <content_id> <action> <fresh-snapshot.json> --expected-revision <当前revision>
```

MCP 对应 `wechat_step(job_id, content_id, action, expected_revision, snapshot)`。
每步返回新的 revision 和 next_action。**仅下面两个 action 返回单次副作用许可**。

| action | 前提 / 结果 | Agent 下一步 |
| --- | --- | --- |
| `attach` | 核对账号、真实标签页和 type=77 编辑器，锁定目标 | 不上传，采新快照 |
| `begin_import` | 空白且无导入在途，DOCX 实际字节未改；原子占用一次导入 | 仅在 `mutation_permitted=true` 时上传返回的 `upload_path` 一次 |
| `verify_import` | 完整正文指纹匹配，全部图载入、数量/顺序与画幅正确，无弹窗/本机路径 | 设置标题、摘要、原视频封面、AI 来源；不可改正文 |
| `begin_save` | 再验正文和元数据，原子占用一次保存 | 仅在 `mutation_permitted=true` 时点击“保存为草稿”一次 |
| `saved` | 在相同账号/标签页观察到准确正文及稳定数字 appmsgid | 刷新或重开该草稿 |
| `readback` | 同一 appmsgid、不同 document identity、完整正文和元数据、列表封面佐证 | 使用返回的 `observation` 绑定 |
| `recover_saved` | 已知准确 appmsgid，另一个可控标签页读到同账号、同稿正文和列表记录 | 只重新锁定读取目标，再刷新回读；不授予新建/保存许可 |

保存后地址栏没有 ID 时，先在独立列表视图找候选，再打开并核对**同一篇**；正文匹配且有
准确 ID 后才调用 `saved`。禁止用同标题就宣告保存成功，也禁止再次点击保存来“试试看”。
导入失败仅在同一目标确实显示失败、正文仍为空且不在转换中时允许一次重试；达到预算后保留现场。
`save_pending` 没有自动重试：外部保存是否发生未确定，不能假装具有 exactly-once 保证。
任何重启/换 Agent 都从 prepare 读取状态，不从历史上传脚本启动。

## 4. 绑定，才算完成

将 `readback` 返回的 `observation` 原样写入当前 run 下的 JSON，再执行：

```text
python -m video_content.cli --config <config> --home <home> wechat bind <job_id> <content_id> <observation.json>
```

修订带 `--supersedes-receipt-id <prepare返回的旧receipt_id>`。bind 再次验证 Content、图片、
封面、AI 声明及刷新回读，并拒绝与 checkpoint 不同的手写通过标志。`job_update` 也不能跳过 Receipt 把微信任务直接标为完成。真实浏览器操作仍由调用方
负责；程序无法阻止绕开入口直接乱点，因此不得声称离线模拟等于微信实测通过。

## 编辑器丢失的恢复（reconcile_abandoned_import）

`import_pending` 的未保存编辑器可能因浏览器重启、标签页关闭而不可恢复。只有同时满足以下证据，
才允许把 Job 恢复到 `prepared`，且导入预算不重置：

1. 钉住的标签页以新 document identity 呈现为空白页（`page_kind=blank`），或同一浏览器中钉住的
   `tab_id` 已不存在（`abandoned_editor.kind=tab_absent`，附当前标签页枚举）；
2. 同一浏览器/账号的完整、未筛选草稿清单（`loaded_all` + 条数吻合）中没有任何 Job 创建时间
   之后的条目，也没有同名草稿；
3. 清单读取目标与原编辑器同属一个浏览器。

恢复后 `begin_import` 被禁止（DOCX 已两次失败过），唯一路线是 `begin_clipboard` 的受控备用传输。

## 备用传输的交付与补发

`begin_clipboard` 原子预约一次粘贴并生成与 DOCX 完全一致的全文和有序原图。程序会尝试写入
Windows 剪贴板；若宿主会话没有交互式剪贴板权限（win32 ERROR_ACCESS_DENIED），步骤仍然签发
`paste_canonical_clipboard_once`，并标记 `clipboard_delivery=agent_delivery_required`：由 Agent
在交互式会话中交付同一载荷（例如微信编辑器接受 DataTransfer 的粘贴事件），载荷 SHA-256 必须与
checkpoint 一致。交付失败后允许一次同载荷补发；内容变更或重复补发一律拒绝。`verify_import`
仍是真实证据：正文指纹、图片数量/顺序、微信托管与画幅全部核对后才算导入成功。

采集浏览器快照时注意：多行 JS 经 Windows .cmd 包装会被截断，长脚本须压缩为单行或用 Node
直调；CLI 标准输出在 Windows 控制台按 GBK 编码，跨进程抓取含中文的 observation 必须从
checkpoint 文件读取，不能依赖控制台文本。

## 旧执行未留编辑器、列表也没有稿件

仅无 target/appmsgid 的 legacy `recovery_required` 可使用 `reconcile_absent`。先在正确账号读取完整、未筛选且显示“已加载全部内容”的草稿箱；由 `collectDraftListSnapshot` 采集当前清单。程序要求数量吻合、标题确实存在于可见页面、所有条目早于该 Job 创建时间且无同题稿，才记录恢复证据并回到 `prepared`（仍不授权上传/保存）。任何当期候选、缺页或已绑定目标均拒绝；不能拿此动作重置 `import_pending` 或 `save_pending`。保留旧 checkpoint 和产物，禁止手改状态。

## 已确认失败后的显式备用传输

只有同一未保存编辑器内两次 DOCX 导入都明确报错，正文为空、图片为零、转换已停止时，才可调用 `begin_clipboard`。程序从同一 Content 重建与 DOCX 完全相同的全文和有序原图，验证指纹后原子预约一次粘贴，将瞬态 CF_HTML 写入剪贴板；不生成第二篇稿、不持久化 Base64、不缩文删图。收到 `paste_canonical_clipboard_once` 后关闭失败弹窗，在已锁定正文中粘贴一次，继续 `verify_import → begin_save → saved → readback → bind`。只要正文已有内容、结果未决、正在转换或预算已消费就拒绝备用传输；仍禁止隐式或混合覆盖。

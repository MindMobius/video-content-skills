# Bilibili 稍后再看到微信公众号草稿自动化

本文说明如何运行仓库提供的“稍后再看 -> 最佳字幕 -> 微信公众号文章 -> 已保存草稿”自动化能力。
详细的 Agent 决策规则以
[`.agents/skills/video-watch-later-automation/SKILL.md`](../.agents/skills/video-watch-later-automation/SKILL.md)
为准。

## 用户体验

正常情况下，用户只做一件事：把视频加入 Bilibili“稍后再看”。后续每次调度由 Agent 自动完成：

1. 读取稍后再看列表并发现新增条目；
2. 按 BVID、分 P、自动化 profile 版本去重并入队；
3. 独立获取平台字幕、硬字幕 OCR、音频 ASR 等证据；
4. 由 Agent 比较冲突并保存可追溯的最佳字幕；
5. 生成、审计并在必要时有限修复微信公众号文章；
6. 在已有登录态和有效授权下保存一份微信草稿；
7. 校验草稿回执并绑定任务，后续周期不再重复创建。

证据或内容在物理上不足时，任务以 `unprocessable` 结束。系统不会要求用户猜测视频中不存在的信息，也不会为了“有结果”而编造内容。登录态失效时使用 `paused_auth`，恢复可见登录态后再继续。

## 运行边界

仓库只提供**一次扫描、一次状态推进、一次交接**的持久操作，不创建隐藏常驻进程。周期由调用方负责，例如 Codex automation、计划任务或其他 Agent 调度器。repository implementation alone does not register a recurring automation。

自动化只允许 `save_wechat_draft`。无论 profile、Skill 还是浏览器页面出现什么控件，都不得发布、群发、定时、声明原创、开启变现或管理账号。有效回执必须包含 `published=false` 和 `publish_actions_performed=[]`。

当前 URL 来源仅支持 Bilibili。自动化不会删除、重排或标记“稍后再看”条目，也不会把多个视频合并为一篇文章。

## 一次性环境准备

### 1. Bootstrap 所需能力

从仓库根目录执行：

```powershell
python scripts/bootstrap.py --apply `
  --config .\.video-subtitle-local\config.json `
  --capability watch_later_monitor
```

也可以通过已安装 CLI 检查：

```powershell
video-subtitle --config .\.video-subtitle-local\config.json `
  setup --capability watch_later_monitor
video-subtitle --config .\.video-subtitle-local\config.json `
  doctor --capability watch_later_monitor
```

`watch_later_monitor` 需要 Python、Node.js、固定版本 OpenCLI、仓库自带的只读 Watch Later 插件，以及一个已连接并登录 Bilibili 的 Browser Bridge profile。依赖安装和路径发现由 Agent 完成；浏览器登录是人类边界。不要把 Cookie、密码或 token 发给 Agent。

### 2. 验证 OpenCLI 插件

能力 setup 会先把插件安装作为 Agent action，再把浏览器登录作为 human action。手工排查时可运行：

```powershell
npm install -g @jackwener/opencli@1.8.6
opencli plugin install file://./opencli-plugin
opencli video-subtitle-watch-later --help
opencli validate video-subtitle-watch-later/list
```

插件只读取 Bilibili `/x/v2/history/toview` 的可见登录会话，不修改稍后再看列表，也不导出登录秘密。

## 创建自动化 profile

准备 `profile-input.json`：

```json
{
  "enabled": true,
  "source": {
    "kind": "bilibili_watch_later",
    "account_profile_alias": "bilibili-main",
    "poll_interval_seconds": 900
  },
  "content": {
    "medium": "wechat_article",
    "objective": "faithful_information_transfer",
    "audience": "公众号读者",
    "output_language": "zh-CN",
    "style": "restrained-editorial",
    "image_policy": "source_video_only"
  },
  "evidence_policy": {
    "require_hard_subtitle_assessment": true,
    "allow_platform_subtitle": true,
    "allow_hard_ocr": true,
    "allow_audio_asr": true
  },
  "retry_policy": {
    "max_technical_attempts": 3,
    "max_content_repairs": 2,
    "backoff_seconds": 300
  },
  "draft_authorization_id": "auth-watch-later-main",
  "prohibited_actions": [
    "publish",
    "mass_send",
    "schedule",
    "originality",
    "account_management"
  ]
}
```

保存并获得稳定的 `profile_id` 与版本：

```powershell
video-subtitle automation-profile-save `
  --document .\profile-input.json `
  --output .\profile.json
```

profile 内容变化会增加版本。同一视频在不同 profile 版本下是不同任务身份，便于明确重跑边界。

## 创建仅限草稿的长期授权

把上一步输出的 `profile_id` 写入 `authorization-input.json`：

```json
{
  "authorization_id": "auth-watch-later-main",
  "status": "active",
  "profile_ids": ["profile_xxxxxxxxxxxxxxxx"],
  "browser_profile_alias": "wechat-main",
  "allowed_actions": ["save_wechat_draft"],
  "prohibited_actions": [
    "publish",
    "mass_send",
    "schedule",
    "originality",
    "account_management"
  ],
  "expires_at": null,
  "revoked_at": null
}
```

必须显式确认该授权只用于保存草稿：

```powershell
video-subtitle automation-authorize-drafts `
  --document .\authorization-input.json `
  --output .\authorization.json `
  --confirm-draft-only-authorization
```

授权可以撤销或设置到期时间。Agent 不得自行扩大、续期或替换授权，也不得保存浏览器秘密。

## 运行一次调度周期

扫描命令只执行一次：

```powershell
video-subtitle automation-scan `
  --profile .\profile.json `
  --store .\.video-subtitle-automation `
  --baseline-if-empty

video-subtitle automation-jobs `
  --store .\.video-subtitle-automation
```

`--baseline-if-empty` 只在全新 store 第一次运行时建立基线，不会为当时已经存在的条目创建任务。之后扫描会把真正新增的 `new_entries` 幂等加入队列。

可用 `automation-job --job <job.json>` 查看单条任务。确定性状态操作优先使用组合命令：

```powershell
video-subtitle automation-evidence-begin `
  --job .\jobs\auto_x\job.json

video-subtitle automation-evidence-complete `
  --job .\jobs\auto_x\job.json `
  --manifest .\jobs\auto_x\evidence\manifest.json

video-subtitle automation-canonical-save `
  --job .\jobs\auto_x\job.json `
  --manifest .\jobs\auto_x\evidence\manifest.json `
  --document .\canonical-input.json
```

组合命令负责状态转换、路径规范化、artifact 绑定和不可用结果的失败关闭。Agent 仍负责：

- 独立判断连续硬字幕是否存在；
- 对平台字幕、OCR、ASR 和 reviewed 证据做多重校验；
- 编写规范字幕及未解决歧义；
- 通过 `video-to-content` 生成、修复和审计文章；
- 在可见微信编辑器中语义操作并核验保存结果。

文章项目通过审计后调用 `prepare_video_automation_handoff`。已有 binding 时跳过浏览器；没有 binding 时只执行授权范围内的 `save_wechat_draft`，生成已验证回执后调用 `bind_video_automation_handoff`。binding 默认保存为 `<job>/handoff-binding.json`，调用方通常不需要构造 output 路径。

相同条目再次扫描时不会产生新任务。已有有效 handoff binding 时不会再次触碰微信编辑器，也不会创建第二份草稿。

latest Watch Later snapshot 是增量检查点。只有当全部新增任务都已持久创建并进入队列后才更新；中断后的下一次扫描会基于旧检查点恢复已有 `discovered` 任务。Bilibili API `-352`、voucher challenge、HTTP 403 和 HTTP 412 统一分类为 `BILIBILI_RISK_CONTROL`，进入技术重试而不是 `paused_auth`。

## 状态与失败处理

| 状态 | 含义 | 自动动作 |
| --- | --- | --- |
| `queued` | 新视频已进入队列 | 开始证据阶段 |
| `retry_wait` | 网络、子进程、服务或浏览器控制暂时失败 | 按 profile 的次数与退避策略重试 |
| `paused_auth` | Bilibili 或微信可见登录态失效 | 保留任务，等待用户恢复登录；不索要凭证 |
| `unprocessable` | 证据物理不足、冲突不可解或文章无法在有限修复内通过审计 | 记录原因并终止，不询问用户如何补造内容 |
| `failed_retry_exhausted` | 技术重试次数耗尽 | 记录最终技术错误 |
| `completed` | 草稿回执和 automation binding 均已验证 | 后续周期直接复用，不重复保存 |

原始平台、OCR、ASR 和 reviewed 证据保持不可变；canonical subtitle 是派生证据，不会覆盖原始文件。subtitle manifest 是持续追加派生元数据的 ledger，因此审计允许由 canonical report 证明的历史 hash pin，不会把合法的 canonical 写入误判为原始证据漂移。

## 完整性审计

每轮队列处理结束后运行：

```powershell
video-subtitle automation-audit `
  --store .\.video-subtitle-automation
```

审计会统一检查：

- job artifact 是否仍位于对应 job 目录；
- 文件是否存在、SHA-256 是否匹配；
- completed job 是否拥有有效 binding 和 receipt；
- receipt 是否保持 `published=false` 且没有发布动作；
- `appmsgid` 是否跨任务唯一；
- 是否存在旧调用方式产生的重复嵌套路径。

只有旧路径元数据且 job 目录内存在哈希完全一致的规范文件时，才可以运行：

```powershell
video-subtitle automation-audit `
  --store .\.video-subtitle-automation `
  --repair-paths
```

修复只更新 `job.json` 中的相对路径，不移动、不删除、不覆盖任何 artifact。

## MCP 对应工具

MCP 暴露与 CLI 同一套持久契约：

- `save_video_automation_profile`
- `authorize_video_automation_drafts`
- `scan_bilibili_watch_later`
- `list_video_automation_jobs` / `get_video_automation_job`
- `begin_video_automation_evidence`
- `complete_video_automation_evidence`
- `save_video_automation_canonical_subtitle`
- `audit_video_automation_store`
- `update_video_automation_job`（兼容和特殊失败转换）
- `save_canonical_subtitle` / `get_canonical_subtitle`（非自动化或兼容调用）
- `initialize_automated_video_content`
- `prepare_video_automation_handoff`
- `bind_video_automation_handoff`

## 调度建议

每次唤醒执行一个短周期：

1. `automation-scan`；
2. 列出非终态任务；
3. 使用组合动作推进确定性阶段，Agent 处理语义阶段；
4. 运行 `automation-audit`；
5. 保存状态并退出。

不要并发运行两个写入同一 `--store` 的周期。OCR 与 ASR 共用 GPU 时严格串行，内容写作可以与非 GPU 任务并行，微信编辑器交接保持串行。不要根据列表移除来取消已提交任务；取消必须是单独、明确的用户操作。

## 确定性与真实验收

离线验收运行：

```powershell
python scripts/repro_check.py --require-tier core --require-tier agent
```

Agent tier 中的 `watch_later_to_draft_contract` 会验证：一个新增条目只生成一个任务；组合动作生成 canonical、内容和一个 binding；第二周期没有重复任务或草稿；不可用证据在内容阶段之前结束；原始证据哈希不变；artifact 路径规范；整库审计通过；所有发布字段为 false。

真实 Bilibili、OCR/ASR 和微信草稿交接始终属于 live tier，状态为 `manual_required`。只有在当前登录态、代表性视频和单独授权都存在时才能做 live acceptance。实现代码本身不会注册真实周期任务，也不会修改稍后再看列表。

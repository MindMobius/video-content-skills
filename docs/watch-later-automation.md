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

`--baseline-if-empty` ????????????????????????????????
??????????????`new_entries` ??????????????????????????
?????????????

可用 `automation-job --job <job.json>` 查看单条任务。周期调度器随后让 Agent 处理可运行任务；不要用固定脚本替代以下语义步骤：

- 独立判断连续硬字幕是否存在；
- 对平台字幕、OCR、ASR 和人工审阅证据做多重校验；
- 调用 `save_canonical_subtitle` 保存 Agent 编写的最佳字幕；
- 调用 `initialize_automated_video_content`，再由 `video-to-content` 生成并审计文章；
- 调用 `prepare_video_automation_handoff` 检查授权和既有 binding；
- 仅在需要时进入微信编辑器，生成已验证回执后调用 `bind_video_automation_handoff`。

相同条目再次扫描时不会产生新任务。已有有效 handoff binding 时不会再次触碰微信编辑器，也不会创建第二份草稿。

## 状态与失败处理

| 状态 | 含义 | 自动动作 |
| --- | --- | --- |
| `queued` | 新视频已进入队列 | 开始证据阶段 |
| `retry_wait` | 网络、子进程、服务或浏览器控制暂时失败 | 按 profile 的次数与退避策略重试 |
| `paused_auth` | Bilibili 或微信可见登录态失效 | 保留任务，等待用户恢复登录；不索要凭证 |
| `unprocessable` | 证据物理不足、冲突不可解或文章无法在有限修复内通过审计 | 记录原因并终止，不询问用户如何补造内容 |
| `failed_retry_exhausted` | 技术重试次数耗尽 | 记录最终技术错误 |
| `completed` | 草稿回执和 automation binding 均已验证 | 后续周期直接复用，不重复保存 |

原始平台、OCR、ASR 和 reviewed 证据保持不可变；canonical subtitle 是派生证据，不会覆盖原始文件。

## MCP 对应工具

MCP 暴露与 CLI 同一套持久契约：

- `save_video_automation_profile`
- `authorize_video_automation_drafts`
- `scan_bilibili_watch_later`
- `list_video_automation_jobs` / `get_video_automation_job`
- `update_video_automation_job`
- `save_canonical_subtitle` / `get_canonical_subtitle`
- `initialize_automated_video_content`
- `prepare_video_automation_handoff`
- `bind_video_automation_handoff`

## 调度建议

每次唤醒执行一个短周期：

1. `automation-scan`；
2. 列出非终态任务；
3. 按任务逐条恢复到下一个安全状态；
4. 保存所有状态后退出。

不要并发运行两个写入同一 `--store` 的周期。仓库已有文件锁和幂等键，但调度器仍应避免无意义的重复工作。不要根据列表移除来取消已提交任务；取消必须是单独、明确的用户操作。

## 确定性与真实验收

离线验收运行：

```powershell
python scripts/repro_check.py --require-tier core --require-tier agent
```

Agent tier 中的 `watch_later_to_draft_contract` 会验证：一个新增条目只生成一个任务；可用证据生成 canonical、内容和一个 binding；第二周期没有重复任务或草稿；不可用证据在内容阶段之前结束；原始证据哈希不变；所有发布字段为 false。

真实 Bilibili、OCR/ASR 和微信草稿交接始终属于 live tier，状态为 `manual_required`。只有在当前登录态、代表性视频和单独授权都存在时才能做 live acceptance。实现代码本身不会注册真实周期任务，也不会修改稍后再看列表。

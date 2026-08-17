# Video Content Skills 1.0 Clean-slate 设计

- 日期：2026-08-17
- 状态：已批准
- 分支：`codex/video-content-clean-slate`

## 1. 背景与结论

这个仓库最初从“提取视频字幕”出发，逐步长成了 Bilibili 获取、平台字幕、OCR、ASR、证据校验、内容改写、稍后再看队列和微信公众号草稿交接的完整链路。真实的 13 条稍后再看任务已经证明：用户真正需要的不是一组独立命令，而是只提供视频或把视频放进稍后再看，Agent 自行完成证据获取、内容生成、审计和草稿保存。

现有实现的问题不是能力不足，而是开发过程留下了过多中间抽象：`project`、`batch`、`phase`、`operation`、`binding` 以及 generic/automation 两套 wrapper 同时存在；CLI 和 MCP 暴露约四十个平铺入口；旧的 `video-subtitle` 命名已经无法表达项目边界。继续兼容这些结构只会把临时历史固化成长期产品契约。

因此 1.0 采用硬切 clean-slate：保留已经被真实流程验证的底层能力和不可变证据，重新建立简洁统一的模型、命令和 Skill，不保留旧模块、旧 CLI、旧环境变量或长期兼容别名。

## 2. 产品定位

**Video Content Skills 是一组供 Agent 渐进式读取和组合的视频证据与内容生产技能。**

它解决四件事：

1. 从受支持的视频来源取得可靠、可追溯的字幕证据；
2. 由 Agent 对多来源证据进行判断，形成规范 Transcript；
3. 按用户指定载体把 Transcript 转成经过审计的内容；
4. 在明确授权下把内容交接到已有登录状态的微信公众号草稿箱，但永不发布。

README 只负责让 Agent 快速理解意义、能力和阅读路由。详细规则放在四个 Skill 及其按需引用的文档、脚本和 schema 中，不再把所有操作手册堆进 README。

## 3. 命名硬切

| 范围 | 1.0 名称 |
| --- | --- |
| GitHub 仓库 / Python 分发包 | `video-content-skills` |
| Python 模块 | `video_content` |
| CLI | `video-content` |
| MCP 命令 | `video-content-mcp` |
| MCP Server | `video_content` |
| 环境变量 | `VIDEO_CONTENT_*` |
| 本地状态目录 | `.video-content` |
| 项目级 schema | `video-content/*` |
| NPM workspace | `video-content-skills`，`private=true` |
| 版本 | `1.0.0` |

旧的 `video-subtitle-*`、`video_subtitle`、`VIDEO_SUBTITLE_*` 和 `.video-subtitle*` 不作为兼容入口。历史运行数据只归档和一次性迁移，不在运行时代码中维持双写或别名。

## 4. Skill 结构

`.agents/skills/` 是唯一 canonical source，只保留四个入口：

### 4.1 `video-evidence`

处理视频 URL、本地视频/音频/字幕、Bilibili 元数据与平台字幕、下载缓存、硬字幕侦察、VideOCR、ASR 和证据核验。输出 Evidence 与可供 Agent 规范化的证据材料。

### 4.2 `video-to-content`

在可信 Transcript 已存在且用户要求内容载体时使用。负责文章结构、来源约束、原封面和时间戳帧、微信 manuscript/render/audit 等内容侧规则。

### 4.3 `watch-later-to-wechat`

编排授权的 Bilibili 稍后再看 → 微信草稿循环。它只提供一次扫描和队列推进能力，定时触发由 Codex automation 或调用 Agent 负责，不创建隐藏 daemon。

### 4.4 `wechat-draft`

在用户明确授权、微信编辑器已经登录、Content 已审计后使用。它只准备、绑定和验证草稿收据，允许保存草稿，永不发布、群发、声明原创或修改账号设置。

每个 Skill 的 `SKILL.md` 只包含触发条件、不可违反的边界、主流程和渐进式引用路由。低频细节进入 `references/`，可执行逻辑进入 `scripts/`，避免 Agent 每次加载全部上下文。

## 5. 六种核心持久产物

系统只承认六种业务产物，其他过程信息作为其中的字段、事件或 Artifact 存在。

### 5.1 Profile

描述一个经过授权的自动化配置：来源、选择的内容载体、微信交接策略、扫描基线、缓存位置和非秘密运行偏好。Profile 不存 cookie、密码、token 或浏览器存储。

### 5.2 Job

统一表示一次视频处理任务。Job 包含：

- `job_id`、可选 `run_id`；
- 输入来源与稳定 source identity；
- 当前 stage 与 status；
- 尝试次数、下一次重试时间和最后错误；
- 六类产物的引用；
- 幂等键和状态事件；
- `completed`、`unprocessable`、`paused_auth` 等终态。

多视频运行通过共享 `run_id` 和 Job 查询组织，不再建立独立 batch ledger。

### 5.3 Evidence

不可变地记录平台字幕、OCR、ASR、媒体清单、侦察结果、封面和时间戳帧等原始观察。不同来源永不互相覆盖；修订通过新 Artifact 与 provenance 关系表达。

### 5.4 Transcript

Agent 基于 Evidence 形成的规范字幕。必须记录使用了哪些证据、做了哪些校正、未解决的不确定性和质量结论。Transcript 是内容转换的唯一正文证据入口。

### 5.5 Content

由 Transcript 转换出的载体内容，包括 manuscript、媒体计划、渲染结果和 audit。Content 不代表平台状态，也不隐含保存或发布授权。

### 5.6 Draft Receipt

微信草稿交接的可验证结果。必须与当前 Content 和可见编辑器状态绑定，包含草稿唯一性证据和刷新回读结果，并强制 `published=false`。它不保存剪贴板正文、cookie、URL token 或浏览器存储。

## 6. Store 与文件布局

默认根目录由 `VIDEO_CONTENT_HOME` 或平台约定目录决定，推荐布局：

```text
.video-content/
  config.json
  profiles/<profile_id>.json
  jobs/<job_id>/job.json
  jobs/<job_id>/events.jsonl
  jobs/<job_id>/artifacts/<artifact_id>.*
  cache/media/
  locks/
```

Store 提供原子写入、内容哈希、相对路径约束和按 `job_id` / `run_id` / status 查询。业务模型只保存相对引用和哈希；原始证据文件一经登记不得原地改写。

不再创建 project 目录树、batch manifest、phase 计时文件、operation wrapper 或两套 canonical automation 结构。

## 7. CLI 与 MCP 能力面

MCP 使用清晰、稳定的 Agent 动作名：

```text
system_setup
system_configure
system_doctor
source_inspect
evidence_start
job_get
artifact_list
artifact_read
transcript_save
content_save
content_validate
watch_later_scan
job_list
job_update
wechat_prepare
wechat_bind
```

CLI 使用同一服务层，但以资源分组：

```text
video-content system ...
video-content source ...
video-content evidence ...
video-content job ...
video-content content ...
video-content watch-later ...
video-content wechat ...
```

CLI 和 MCP 只做参数解析与 JSON 输入输出，不复制业务逻辑。同步重活和后台 Job 使用同一个 Store、同一种状态机和同一组产物契约。

## 8. 主流程

### 8.1 单视频

```text
input
  -> source_inspect
  -> evidence_start
  -> Agent 检查平台字幕与视觉硬字幕
  -> 必要时 OCR / ASR（共享 GPU 串行）
  -> transcript_save
  -> 用户要求载体时 content_save + content_validate
  -> 用户明确授权微信草稿时 wechat_prepare + 可见浏览器操作 + wechat_bind
```

### 8.2 稍后再看自动化

```text
watch_later_scan(profile)
  -> 与 Profile 基线比较
  -> 为新增视频创建幂等 Job
  -> Agent/automation 逐个推进 Job
  -> 技术失败按策略重试
  -> 物理证据不足标记 unprocessable
  -> 真正登录边界标记 paused_auth
  -> 完成后更新基线
```

“无法取得足够证据”是物理结果，不向用户反复询问；系统记录 `unprocessable` 后继续处理下一条。普通安装、路径发现和技术重试由 Agent 处理。

## 9. 必须保留的实现能力

- Bilibili 元数据、平台字幕和稍后再看读取；
- 下载与跨重试持久媒体缓存；
- VideOCR、ASR 及深度 doctor；
- 平台、OCR、ASR、reviewed evidence 分开保存；
- Agent 对证据进行规范化，不依赖固定审阅窗口；
- 原视频封面和时间戳帧作为默认配图；
- 第一方微信文章 renderer；
- Browser Bridge 可见状态交接；
- 草稿唯一性、刷新回读和 validated receipt；
- `published=false`；
- 技术失败重试、`unprocessable`、`paused_auth`；
- GPU 串行、任务恢复和幂等。

## 10. 明确删除的实现

- `dsh/` 与 DeepSeek Harness bundle；
- 根 NPM 对外发布 bundle、exports 和 DSH 元数据；
- 固定字幕审阅窗口三个入口；
- `start_video_content_phase` / `finish_video_content_phase`；
- batch manifest 和独立 batch API；
- portable ZIP bundle 协议；
- generic 与 automation 两套重复 wrapper；
- 旧 Skill 名称；
- 旧项目名称、schema 前缀、发布配置和相应测试；
- 只记录开发过程、没有持续维护价值的案例和计划文档。

删除表示从 1.0 产品契约中移除，而不是先复制到新的 legacy 目录。未来出现真实需求时再基于六产物模型重新设计。

## 11. 历史数据迁移

旧 `.video-subtitle-local` 必须先停止写入，再整体移到仓库外的只读归档；任何平台字幕、OCR、ASR、规范字幕、文章、收据和媒体都不得删除。

一次性迁移只提取新系统继续运行所需的：

- Profile 的非秘密设置与稍后再看基线；
- 已完成视频的 source identity / 幂等标记，防止重复处理或重复保存 13 条草稿；
- 授权状态的非秘密引用；
- 媒体缓存，以链接、复制或受控移动方式进入新缓存。

迁移工具产生清单和哈希报告。1.0 运行时代码不读取旧目录，也不提供长期 legacy adapter。

## 12. 安全与授权边界

- 不请求或持久化 cookie、密码和 token；
- 浏览器登录、硬件缺失、操作系统权限提示和确认的大下载是人工边界；
- 微信操作只复用已经可见的登录状态；
- 永不发布、群发、排期、声明原创、变现或管理账号；
- 默认配图仅来自原封面和时间戳帧，除非用户另行明确要求；
- Browser Bridge 观察只保存无秘密状态合同和收据；
- 外部平台写操作必须有当前用户授权，历史 Profile 不能代替发布授权。

## 13. 验证策略

1. 契约测试：六产物 schema、状态转换、不可变 Artifact、路径与秘密扫描；
2. 服务测试：CLI 与 MCP 对同一服务层的输入输出一致；
3. 能力回归：Bilibili fixture、OCR/ASR plan、renderer、Watch Later 幂等、WeChat receipt；
4. 端到端 fixture：从 source inspection 到 validated Draft Receipt 的完整离线样例；
5. 打包检查：Python wheel/sdist 和私有 NPM workspace 文件边界；
6. 复现检查：core 与 agent tier；
7. live tier 保持人工：当前 Bilibili/Browser Bridge、代表性 OCR/ASR 和单独授权的微信编辑器操作。

编译、测试或路径存在都不能替代真实能力验证。最终报告必须分别说明离线验证、重运行验证、历史数据迁移和 live 边界。

## 14. 完成标准

- 仓库中不存在活动的旧项目名称、旧模块、旧 CLI 或旧 schema；
- 只有四个 canonical Skill，README 能在短篇幅内完成 Agent 路由；
- CLI/MCP 只暴露批准的最小能力面；
- 六产物模型覆盖单视频和稍后再看两条流程；
- 保留能力的测试全部通过，删除能力不再被打包或文档引用；
- 13 条历史成果已归档且新系统具有防重复基线；
- 版本为 `1.0.0`，完整验证通过；
- 中文提交推送并快进合入 `main`。

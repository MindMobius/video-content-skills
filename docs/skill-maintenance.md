# Skill 维护指南

本文件面向修改 **Video Content Skills** 的 Agent。普通视频处理任务不需要读取它；只有
新增 Skill、修改 Skill 契约、调整工具/schema 或准备发布时才加载。

## 维护目标

项目采用渐进式披露：默认上下文只提供路由和不可违反的边界，任务细节在命中的 Skill
中展开，条件性实现细节再进入 `references/`、脚本或专题文档。

维护时优先保证：

1. Agent 能从用户意图稳定路由到正确 Skill；
2. Skill 能发现完成任务所需的工具、契约和深层资料；
3. 确定性代码负责状态、安全与可复现性，Agent 负责语义判断；
4. 已有 CLI、MCP、schema、配置和持久化产物保持兼容；
5. 默认上下文不因新增能力无限增长。

## 唯一规范源

所有项目 Skill 的唯一规范目录是：

```text
.agents/skills/<skill-name>/
```

不要在 `.codex/skills/`、个人目录或其他 Agent 专用目录维护第二份源码。需要安装到其他
环境时，使用 Skill installer 链接或复制规范源；修改必须回到本仓库。

每个可发现 Skill 至少包含：

- `SKILL.md`：任务触发条件、强制流程、工具边界和完成条件；
- `agents/openai.yaml`：显示名称、简短描述和包含 `$<skill-name>` 的默认提示；
- 可选 `references/`：只在具体步骤需要时读取的详细规则；
- 可选 `scripts/`：确定性、可测试、可复用的执行辅助；
- 可选 `examples/` 或 `templates/`：帮助 Agent 理解产物，而不是替代 schema。

## 修改现有 Skill 还是新增 Skill

优先修改现有 Skill，当变化仍属于它的责任边界，例如：

- 增加同一证据阶段的新工具；
- 强化已有授权、失败分类或验收条件；
- 把过长的条件性说明拆入 `references/`；
- 为同一载体增加兼容路径。

只有同时满足以下条件时才新增 Skill：

- 用户意图可以被独立识别；
- 它有独立的授权或完成边界；
- 加入现有 Skill 会让默认流程产生明显分支或误触发风险；
- 它能复用现有确定性工具，而不是复制另一套实现。

不要因为某个步骤很长就自动新建 Skill；先判断它是不是当前任务的一段条件性深度。

## 渐进式文档规则

### `README.md`

README 是项目地图，只保留意义、能力、路由、维护入口、兼容说明和最小验证。不要把 CLI、
MCP、安装矩阵或平台操作手册复制回 README。

### `AGENTS.md`

AGENTS.md 会进入所有仓库任务的上下文，只保留全局不变量：Skill 路由、证据边界、授权
边界、资源调度、兼容策略和验证命令。具体命令和工具参数应链接到 Skill 或专题文档。

### `SKILL.md`

SKILL.md 是任务执行契约，应包含：

- frontmatter 中稳定的 `name` 和清晰的 `description`；
- 何时使用、何时不要使用；
- 必须完整执行的阶段；
- Agent 与工具的责任分工；
- 授权、错误、幂等和完成条件；
- 指向深层资料的相对链接。

不要把所有实现背景都放进 SKILL.md。Agent 在执行关键路径时必须直接看到的内容留下；只有
特定平台、载体、工具或异常才需要的内容放进 `references/`。

### `references/`

references 文件应按“何时读取”命名和链接，例如环境安装、证据决策、载体格式、浏览器
检查清单。每个 reference 只解决一个相对稳定的问题，不复制 SKILL.md 的强制边界。

### `docs/`

专题文档解释跨 Skill 架构、运行时、维护和验收；`docs/plans/` 保存历史设计与实施计划；
`docs/cases/` 保存可追溯案例。历史文件不作为当前执行规范，也不因品牌调整被批量改写。

## 契约同步

修改行为时先确定真值源，再同步所有公共入口：

| 变化 | 必须检查 |
| --- | --- |
| 新增或重命名 MCP 工具 | `src/video_subtitle/mcp_server.py`、CLI、Skill 工具表、smoke 测试 |
| 新增持久化产物 | schema、读写代码、验证器、Skill 完成条件、复现检查 |
| 修改环境能力 | requirements、bootstrap/setup、doctor、`docs/environment.md` |
| 修改证据策略 | `video-subtitle` Skill、证据代码、`docs/workflow.md`、测试 |
| 修改内容载体 | `video-to-content` Skill、references、renderer、审计测试 |
| 修改微信交接 | handoff Skill、browser adapter、receipt validator、live 边界 |
| 修改自动化状态 | profile/job schema、CLI/MCP、automation Skill、完整性审计 |

工具名称、参数和 schema 字段必须由代码或 schema 定义；文档只引用，不发明第二套术语。

## 兼容策略

项目品牌可以演化，但已被 Agent 和持久化产物引用的标识默认稳定。本版本保留：

- 分发包 `video-subtitle-skill`；
- CLI `video-subtitle`、`video-subtitle-mcp`；
- Python 模块 `video_subtitle`；
- 配置目录 `.video-subtitle-local`；
- 已有 Skill 名称和 schema ID。

必须破坏兼容时，先设计迁移层、双读或别名，再修改规范标识。不能通过全局字符串替换完成
运行时更名，也不能让旧任务、草稿绑定或 portable bundle 在没有诊断信息的情况下失效。

版本遵循语义化版本：

- PATCH：兼容的修复和文档澄清；
- MINOR：兼容的新能力、Skill 或对外定位调整；
- MAJOR：经过迁移设计批准的破坏性契约变化。

所有版本来源必须同步：Python 项目、模块 `__version__`、NPM package、shrinkwrap、lock 和
相关测试。

## 测试策略

行为或公共文档契约变更先写失败用例。优先使用：

- 单元测试验证 schema、状态机、路径和幂等；
- Skill 分发测试验证发现目录、frontmatter、`agents/openai.yaml` 和相对链接；
- 文档架构测试防止 README、AGENTS.md 再次膨胀或路由失效；
- MCP smoke 验证工具发现；
- `scripts/repro_check.py` 验证干净 clone、打包和 Agent 契约。

提交实现前运行：

```text
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

涉及 FFmpeg/FFprobe 时增加 `media` tier；真实 Bilibili、OCR/ASR、Browser Bridge 和微信交接
属于单独授权的 `live` 验收，不得从 fixture 推断成功。

## 修改检查清单

提交前确认：

- [ ] 用户意图能路由到唯一主要 Skill；
- [ ] `SKILL.md` 没有重新堆入只在少数场景需要的背景资料；
- [ ] 新链接使用相对路径且能解析；
- [ ] 新工具或 schema 已同步 CLI、MCP、Skill 和测试；
- [ ] 原始证据、授权和不发布边界没有被削弱；
- [ ] 兼容标识没有被意外重命名；
- [ ] README 和 AGENTS.md 仍然是入口，不是完整手册；
- [ ] 完整验证通过；
- [ ] 提交信息使用中文并准确描述实际变化。

# Video Content Skills 渐进式更名与文档重构设计

## 背景

仓库已经从单一字幕提取 Skill 演化为一组可组合的 Agent-native 能力：

- `video-subtitle` 建立平台字幕、硬字幕 OCR、音频 ASR 等独立证据；
- `video-to-content` 将已核验证据转换为可追溯内容；
- `wechat-draft-handoff` 在明确授权后保存微信公众号草稿；
- `video-watch-later-automation` 编排 Bilibili 稍后再看到微信草稿的长期工作流。

现有仓库名 `video-subtitle-skill`、README 标题和 GitHub 简介仍将项目描述为字幕工具，已经不能覆盖实际边界。同时，README 混合了项目定位、安装教程、CLI/MCP 手册、架构说明和维护规则，不符合 Agent 按任务逐层读取上下文的方式。

## 目标

1. 将对外项目身份调整为 **Video Content Skills**，仓库 slug 调整为 `video-content-skills`。
2. 将 README 改成简洁的 Agent 路由入口，而不是完整操作手册。
3. 将使用、维护、架构和运行时说明分层，让 Agent 只读取当前任务需要的内容。
4. 保留已经投入使用的 CLI、MCP、Python 模块、配置目录、schema 和分发包名称，避免破坏既有自动化。
5. 保留字幕证据、内容审计、草稿授权和不发布边界，不因文档精简降低安全性。

## 非目标

本轮不做以下改动：

- 不重命名 `video-subtitle` CLI 或 `video-subtitle-mcp`；
- 不重命名 `video_subtitle` Python 模块；
- 不迁移 `.video-subtitle-local` 配置目录；
- 不修改 `video-subtitle/*`、`video-content/*` 等既有数据契约标识；
- 不重命名已经发布或被安装器识别的单项 Skill；
- 不改变字幕、内容转换或微信草稿交接的运行行为；
- 不发布 NPM/Python 包，不创建 GitHub Release。

## 名称与兼容策略

### 新的对外身份

- 项目名：`Video Content Skills`
- GitHub 仓库：`MindMobius/video-content-skills`
- 推荐简介：`Agent-native 视频证据与内容生产 Skill 集：字幕校验、内容转换、稍后再看自动化与微信草稿交接。`

### 保留的兼容标识

以下标识继续作为稳定运行接口：

- NPM/Python 分发名：`video-subtitle-skill`
- CLI：`video-subtitle`
- MCP：`video-subtitle-mcp`
- Python 模块：`video_subtitle`
- 本地配置目录：`.video-subtitle-local`
- 已有 Skill 名称和 schema 标识

README 和维护文档必须明确区分“项目品牌”与“兼容运行标识”。仓库链接更新到新地址，旧 GitHub 地址依赖 GitHub 的仓库重定向，不在代码中继续作为规范地址。

## 渐进式文档架构

### 第一层：仓库入口

`README.md` 只承担：

1. 项目意义和能力边界；
2. 四个 Skill 的任务路由；
3. 使用与维护的最短入口；
4. 文档地图；
5. 兼容标识说明；
6. 最小验证命令和安全边界。

README 不再复制长篇 bootstrap、CLI、MCP、OCR/ASR、批次和微信编辑器操作步骤。

### 第二层：自动加载的仓库规则

`AGENTS.md` 保留所有 Agent 都必须知道的内容：

- 按任务读取哪个 Skill；
- `.agents/skills/` 是唯一规范 Skill 源；
- 原始证据不可覆盖；
- 浏览器、授权、草稿和发布边界；
- 多视频批次与幂等原则；
- 修改仓库时的验证入口。

具体安装命令、运行时矩阵、工具清单和操作细节改为链接到对应 Skill 或文档，减少所有任务都必须加载的上下文。

### 第三层：任务 Skill

`.agents/skills/*/SKILL.md` 继续作为执行规范。Agent 只有在任务命中时才完整读取对应 Skill：

- 字幕和证据任务：`video-subtitle`
- 内容转换任务：`video-to-content`
- 稍后再看自动化：`video-watch-later-automation`
- 微信草稿交接：`wechat-draft-handoff`

本轮不大规模重写各 Skill 的语义，仅修正项目级名称、仓库链接和必要路由描述。后续可单独迭代 Skill 内部的 references 分层，避免把文档重构和运行契约重构混在一个版本中。

### 第四层：专题文档

活动文档按意图被 README 和 AGENTS 路由：

| 意图 | 文档 |
| --- | --- |
| 新机器安装与能力准备 | `docs/environment.md` |
| 字幕证据工具架构 | `docs/workflow.md` |
| 从视频证据生成内容 | `docs/content-workflow.md` |
| 稍后再看自动化 | `docs/watch-later-automation.md` |
| 可复现性与验收 | `docs/reproducibility.md` |
| 修改或新增 Skill | `docs/skill-maintenance.md` |
| 具体交付案例 | `docs/cases/` |
| 历史设计与实施记录 | `docs/plans/` |

## Skill 维护文档

新增 `docs/skill-maintenance.md`，内容覆盖：

1. Skill 的唯一规范目录和分发原则；
2. 何时修改现有 Skill，何时新增 Skill；
3. SKILL.md 与 references 的信息分层；
4. 工具、schema、CLI、MCP 与 Skill 文档的同步规则；
5. 向后兼容和版本策略；
6. 测试与可复现性检查；
7. 提交前检查清单。

维护文档服务于“修改项目的 Agent”，不进入普通视频处理任务的默认上下文。

## README 结构

目标 README 控制在约 100 至 160 行，建议结构：

1. 标题与一句话定位；
2. 为什么存在；
3. 能力地图；
4. Agent 任务路由表；
5. 渐进式读取规则；
6. 使用入口；
7. 维护入口；
8. 兼容说明；
9. 核心边界；
10. 最小验证命令。

安装和操作命令只保留一个 bootstrap 入口和验证入口，其余链接到专题文档或 Skill。

## 元数据与版本

- `package.json` 和 `pyproject.toml` 的 description 改为新的项目定位；
- repository/issues URL 改为 `MindMobius/video-content-skills`；
- 保留包名 `video-subtitle-skill`；
- 版本从 `0.7.0` 提升到 `0.8.0`，表达对外定位和文档契约的次版本升级；
- 同步 `src/video_subtitle/__init__.py`、锁文件和测试中的版本断言；
- GitHub Topics 建议使用 `agent`, `agent-skills`, `video`, `subtitle`, `ocr`, `asr`, `bilibili`, `wechat`, `automation`。

## GitHub 变更顺序

1. 在旧仓库地址上完成代码和文档提交并推送；
2. 在 GitHub 设置中将仓库改名为 `video-content-skills`；
3. 更新简介和 Topics；
4. 将本地 `origin` 改为新的规范 URL；
5. 验证新旧 URL、默认分支和远端 HEAD；
6. 不删除旧地址兼容提示，不手工创建第二个仓库。

## 验证策略

文档重构也必须通过仓库完整检查：

```text
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

另外增加面向文档架构的静态测试，确保：

- README 使用新项目名并保持在约定长度内；
- README 包含四个 Skill 的规范入口；
- README 不重新塞入完整 CLI/MCP 手册；
- 维护文档存在并覆盖 Skill 规范源、兼容和验证；
- 活动文档不再把整个项目称为单一 `Video Subtitle Skill`；
- 新仓库 URL 已同步到元数据和活动文档；
- 兼容 CLI、模块和 schema 名称没有被误改。

## 风险控制

- 历史计划和案例保留当时名称，不批量改写历史记录；
- 不用全局字符串替换重命名运行契约；
- GitHub 仓库改名放在代码推送之后，避免中途失去远端；
- 所有外部状态修改完成后再次通过 API/远端引用验证；
- 若 GitHub 登录或权限失效，仅暂停远端元数据更新，不回滚已经验证的本地文档改造。

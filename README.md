# Video Content Skills

Agent-native 视频证据与内容生产 Skill 集：从字幕校验、内容转换，到 Bilibili
稍后再看自动化和微信公众号草稿交接。

项目面向 Agent，而不是把所有步骤暴露给用户。工具负责可复现的采集、状态、产物和
安全边界；Agent 根据任务选择证据、处理冲突、组织内容并决定是否升级取证。

> 项目已经从单一字幕 Skill 演化为 `Video Content Skills`。为保持现有安装和
> 自动化兼容，CLI、Python 模块、schema 和分发包等运行标识暂时继续使用
> `video-subtitle` / `video-subtitle-skill`。

## 为什么存在

理想交互可以只有一个视频链接，或者把视频加入 Bilibili 稍后再看。之后由 Agent 完成：

- 获取平台字幕、硬字幕 OCR 和音频 ASR 等独立证据；
- 保留原始证据并产出可追溯的规范字幕；
- 根据载体重建文章、笔记或其他内容；
- 使用原视频封面和时间戳帧完成配图；
- 在明确授权后保存微信公众号草稿，但绝不发布。

仓库提供确定性基础设施，不试图用固定流程替代 Agent 的语义判断。

## 能力地图

| 能力 | 规范 Skill | 结果 |
| --- | --- | --- |
| 视频、音频、字幕、OCR、ASR 与证据校订 | `video-subtitle` | 独立证据和已核验字幕 |
| 从已核验视频内容生成其他媒介 | `video-to-content` | 内容模型、成品和忠实度审计 |
| Bilibili 稍后再看到微信草稿的周期任务 | `video-watch-later-automation` | 可恢复任务、批次状态和草稿绑定 |
| 将已审计文章保存到已登录微信编辑器 | `wechat-draft-handoff` | 已验证草稿收据，不包含发布动作 |

底层同时提供 JSON CLI、Python MCP Server、schema、渲染器和可复现性检查，供 Skill
组合使用。

## Agent 任务路由

收到任务后先读仓库规则 [`AGENTS.md`](AGENTS.md)，然后只加载命中的 Skill：

- 视频链接、本地媒体、字幕、OCR 或 ASR：
  [`.agents/skills/video-subtitle/SKILL.md`](.agents/skills/video-subtitle/SKILL.md)
- 已有可信字幕，需要生成文章或其他内容：
  [`.agents/skills/video-to-content/SKILL.md`](.agents/skills/video-to-content/SKILL.md)
- 扫描或处理 Bilibili 稍后再看：
  [`.agents/skills/video-watch-later-automation/SKILL.md`](.agents/skills/video-watch-later-automation/SKILL.md)
- 已有审计文章，需要保存微信公众号草稿：
  [`.agents/skills/wechat-draft-handoff/SKILL.md`](.agents/skills/wechat-draft-handoff/SKILL.md)

不要因为仓库包含某个载体就自动选择它。普通单视频任务未指定输出时，先完成字幕证据，
再根据用户要求决定后续载体；已有 Watch Later 自动化 profile 时按其长期授权执行。

## 渐进式读取

Agent 按以下顺序获取上下文，不要一次加载整个仓库：

1. **仓库层**：读取 `AGENTS.md`，确认全局边界和 Skill 路由；
2. **任务层**：完整读取当前任务对应的 `SKILL.md`；
3. **细节层**：仅在 Skill 指向时读取同目录 `references/`、脚本或示例；
4. **专题层**：只有安装、维护、架构或验收任务才读取对应 `docs/`；
5. **历史层**：`docs/plans/` 和 `docs/cases/` 只用于追溯，不是默认执行规范。

Skill 是执行契约，代码和 schema 是确定性契约，专题文档负责解释设计与维护方式。

## 使用入口

新机器从仓库根目录读取一次 bootstrap 契约；之后按 setup 返回的动作和目标 Skill 继续：

```powershell
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --config <config-path> --capability <required-capability>
```

更具体的入口按需求读取：

- 环境与重依赖：[docs/environment.md](docs/environment.md)
- 字幕证据架构：[docs/workflow.md](docs/workflow.md)
- 内容转换：[docs/content-workflow.md](docs/content-workflow.md)
- 稍后再看自动化：[docs/watch-later-automation.md](docs/watch-later-automation.md)
- 可复现性与验收：[docs/reproducibility.md](docs/reproducibility.md)

## 维护入口

修改或新增 Skill 前先读 [docs/skill-maintenance.md](docs/skill-maintenance.md)。核心原则：

- `.agents/skills/` 是唯一规范 Skill 源，不维护第二份副本；
- `SKILL.md` 保留任务契约，条件性细节放入 `references/`；
- 工具、CLI、MCP、schema 和 Skill 文档必须同步；
- 保留已有运行标识，破坏性更名必须提供迁移兼容层；
- 行为变更先写失败用例，完成后运行完整复现检查。

## 核心边界

- 当前 URL 平台支持范围是 Bilibili；
- 平台字幕与画面连续硬字幕是两个独立事实；
- 原始平台、OCR、ASR 和人工校订证据分别保存，不互相覆盖；
- 公众号文章配图默认使用原视频封面和带时间点的可追溯截帧；渲染交接使用单行相对图片路径标记，不生成填充图片；
- OCR 与 ASR 共用 GPU 时严格串行，媒体下载缓存跨重试复用；
- 自动化只提供一次扫描和任务操作，周期由调用方管理，不启动隐藏 daemon；
- 微信交接只使用已有可见登录态，只保存明确授权的草稿；
- 不发布、不群发、不定时、不声明原创，也不读取账号凭证。

## 兼容标识

项目品牌为 `Video Content Skills`，以下名称仍是稳定接口：

- 分发包：`video-subtitle-skill`
- CLI：`video-subtitle`、`video-subtitle-mcp`
- Python 模块：`video_subtitle`
- 本地配置：`.video-subtitle-local`
- 既有 Skill 名称和数据契约 schema ID

## 验证

提交实现变更前运行：

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

`media` tier 只在 FFmpeg/FFprobe 可用时要求；`live` tier 始终需要当前 Bilibili、OCR/ASR、
Browser Bridge 和单独授权的微信编辑器真实状态。

MIT License。

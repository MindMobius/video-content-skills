# Skill 维护

`.agents/skills/` 是唯一规范 Skill 源。README 给 Agent 路由，SKILL 给任务主流程，低频内容
按需进入 references/scripts；不要再把完整手册堆回入口文件。

## 四个 Skill

- `video-evidence`：来源、下载、平台字幕、OCR、ASR、证据判断和 Transcript；
- `video-to-content`：从 Transcript 到载体 Content 和审计；
- `watch-later-to-wechat`：Profile、扫描、队列、重试与三段 Skill 编排；
- `wechat-draft`：可见编辑器交接、保存、刷新回读和 Draft Receipt。

新增 Skill 前先确认它有独立触发条件、独立完成标准和独立风险边界。只是某个现有流程的低频
分支时，优先新增 reference。

## 渐进式层级

### `SKILL.md`

必须让 Agent 直接看到：

- 何时触发、何时不要使用；
- 主流程和完成标准；
- Agent 与工具的责任分工；
- 授权、幂等、错误和安全边界；
- 当前步骤才需要读取的相对链接。

目标是短而完整，不放长篇实现背景、历史案例或全部参数表。

### `references/`

一个文件解决一个稳定问题，例如环境安装、证据判断、载体结构或浏览器检查清单。文件名应
告诉 Agent“什么时候读”，不要复制 SKILL 的硬边界。

### `scripts/`

只放确定性、可测试、可恢复的机械操作。语义判断和视觉判断不应藏进脚本。脚本输出一个
JSON 合同，不写秘密，不静默改变平台状态。

### `agents/openai.yaml`

目录名、frontmatter `name`、`$skill-name` 默认提示必须一致。

## 契约同步

| 变化 | 同时检查 |
| --- | --- |
| 六产物字段 | model、schema、Store/service、CLI/MCP、Skill、测试 |
| CLI/MCP 工具 | `api.py`、CLI、MCP smoke、相关 Skill |
| 环境能力 | requirements、bootstrap/setup、doctor、`video-evidence` reference |
| 证据决策 | evidence/pipeline、`video-evidence`、fixture |
| 内容载体 | content/renderer、`video-to-content`、审计测试 |
| 微信交接 | adapter、observation/receipt、`wechat-draft`、Node/Python 测试 |
| 自动化状态 | Profile/Job、`watch-later-to-wechat`、幂等测试 |

不要添加旧名称兼容入口。1.0 是硬切；历史运行数据通过一次性迁移工具归档和提取基线，运行时
只认新合同。

## 修改步骤

1. 先写失败测试或 fixture；
2. 修改最小实现；
3. 更新对应 Skill/reference，而不是泛改全部文档；
4. 检查相对链接、frontmatter 和无旧标识；
5. 运行完整验证；
6. 使用中文提交信息准确描述变化。

```text
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

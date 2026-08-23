# Skill 维护

`.agents/skills/` 是唯一规范 Skill 源。README 给 Agent 路由，SKILL 给任务主流程，低频内容
按需进入 references/scripts；不要再把完整手册堆回入口文件。

## 四个 Skill

- `video-evidence`：来源、下载、平台字幕、OCR、ASR、证据判断和 Transcript；
- `video-to-content`：从 Transcript 到来源忠实的载体 Content 和审计；
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
- 默认来源忠实以及需要用户明确授权的编辑越界；
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
| 内容载体 | content/renderer、`video-to-content`、来源忠实 reference、审计测试 |
| 微信交接 | adapter、observation/receipt、`wechat-draft`、Node/Python 测试 |
| 自动化状态 | Profile/Job、`watch-later-to-wechat`、幂等测试 |

不要添加旧名称兼容入口。1.0 是硬切；历史运行数据通过一次性迁移工具归档和提取基线，运行时
只认新合同。

## 真实失败如何沉淀

如果真实输出明显不合格，但已有测试全部通过，应把它视为“验收合同缺失”，而不是只在提示词里
补一句提醒。长期规则是：**流程完成不等于内容完成**。

1. 记录用户看到的具体症状，以及旧系统为什么仍判定成功；
2. 找到缺失的完成条件，区分需要 Agent 语义判断的部分和可以确定性验收的事实；
3. 先写失败测试，复现“错误结果仍能通过”的路径；
4. 把稳定默认值写入 Profile，把主流程和判断边界写入 Skill/reference，把客观事实写入
   Schema、验证器和 Receipt；
5. 用真实输出或有代表性的 fixture 回归，不以 renderer、进程退出码、保存 toast 或 Artifact
   数量替代用户实际看到的效果；
6. 同步检查 README/AGENTS、Skill、运行文档和测试，避免只改一个入口。

本项目中，章节是否实质、哪些细节必须保留、截图为何有意义属于 Agent 语义判断；章节是否有
来源到正文的映射、截图是否真的出现在对应 block、AI 创作来源是否刷新回读属于确定性验收。
后者没有证据时，任务必须保持未完成，不能依赖“下次记得”。

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

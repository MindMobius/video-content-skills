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
| 内容载体 | content/renderer、`video-to-content`、来源忠实/表达审校 reference、审计测试 |
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

### 已发生案例：字幕直贴却全流程成功

症状是公众号草稿有标题、图片、摘要、AI 来源声明和有效 Receipt，但正文基本等于逐条字幕。
原因不是微信交接丢内容，而是内容构建脚本只做 cue 机械拼接、定长分段和少量补标点，却无条件
写入 `status=passed`、`reviewed_by=agent`；旧验证器又只检查章节、图片和审计结构，导致假完成
一路进入平台。

修复必须同时落在两边：Skill 明确机械预处理不能冒充 Agent 语义判断；验证器用高重合、低标点
和长无标点片段的组合信号做确定性验收，命中 `raw Transcript passthrough` 时禁止微信交接。该
信号不是文风评分器，也不能通过无意义换词或篡改审计字段绕过。

### 已发生案例：信息完整但 Agent 脚手架仍像模板

症状是文章已经保留视频的章节、细节和截图，却在 Agent 新增的标题、转场、总结或证据边界中
反复出现空转提示语、人造对照和统一句法。旧流程只验证“内容在不在”，没有留下“这些新增语言
是否经过来源感知判断”的可核验结果，因此一篇事实完整的文章仍可能带有明显模板腔。

修复不是全文“去 AI 味”重写，也不是把外部规则命中次数变成分数。`video-to-content` 在完整成稿
之后按需读取表达审校 reference，只最小修改 Agent 新增或载体适配语言，来源真实表达、专业罗列、
问句、比喻和限定优先保留；程序只验证 `expression_audit` 的策略、覆盖范围、决策来源以及
`after` 是否等于最终文档。修改后还必须再次复核来源忠实，不能用“更像人写的”交换信息密度。

### 本轮沉淀的三个验收教训

1. **文章很短不等于文章很干净。** 来源忠实任务的目标是恢复创作者已有表达，不是把长视频压成摘要。
   “看起来简洁”必须回到完整 Transcript，对照实质章节、专业细节、案例、反例和限定判断。
2. **截图存在不等于截图被使用。** `media` 列表、渲染目录和正文 image block 是三个不同事实；只有
   正文中实际出现的图片，且 `visual_plan.block_index` 指向同一 block，才算完成。最低数量只是防漏，
   不能复制相似帧凑数。
3. **平台点击成功不等于平台状态成立。** 选择“内容由AI生成”、点击保存、看到 Toast 或拿到
   `appmsgid` 都要在刷新后的同一草稿中重新回读；没有回读就不能生成有效 Receipt。

这些经验分别落在 `video-to-content` 的 Content 验收与来源感知表达审校、`wechat-draft` 的恢复
清单和程序验证器中，不要只把它们写成一次性的提示词。

### 以后遇到浏览器不确定状态

先重读同一可见目标，再决定重试或暂停：一次 evaluate/Playwright 超时属于技术问题，真实登录页才是
`paused_auth`。在确认当前没有有效 Receipt 之前，不得再次新建草稿；明确修订必须复用同一数字
`appmsgid` 并保留 `supersedes_receipt_id` 历史。

### 经验沉淀模板

每次真实运行发现问题，至少补齐以下六项：

1. 用户实际看到的症状；
2. 旧流程用什么假信号把它判成成功；
3. 缺失的是 Agent 判断还是确定性事实；
4. 能否写成失败测试、Schema/验证器或 Receipt 字段；
5. 应该放在 README、AGENTS、SKILL 还是低频 reference；
6. 下一次如何在不打断用户的前提下安全停止、重试或继续下一 Job。

## 修改步骤

1. 先写失败测试或 fixture；
2. 修改最小实现；
3. 更新对应 Skill/reference，而不是泛改全部文档；
4. 检查相对链接、frontmatter 和无旧标识；
5. 运行完整验证；
6. 使用中文提交信息准确描述变化。

验证优先使用项目锁定环境。宿主 Python 缺少 `pytest`、`ruff` 或项目模块时，先修正运行环境，
不要把环境错误误判成实现回归。

```text
uv run --isolated --locked --all-extras python -m ruff check .
uv run --isolated --locked --all-extras python -m ruff format --check .
uv run --isolated --locked --all-extras python -m pytest
uv run --isolated --locked --all-extras python scripts/mcp_smoke.py
npm test
npm run pack:check
uv run --isolated --locked --all-extras python scripts/repro_check.py --require-tier core --require-tier agent
```

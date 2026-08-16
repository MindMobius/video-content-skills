# Agent 可复现性与验收

## “可复现”的准确含义

本项目承诺的是工作流与证据边界可复现，不承诺不同 Agent、不同模型或不同日期生成逐字
相同的文章和图片。

可复现契约分三层：

1. **确定性工具层**：Bootstrap、setup、CLI/MCP、schema、manifest、版本号与 SHA-256
   必须能被机器检查；相同输入产物的来源和失效关系必须一致。
2. **外部证据层**：平台页面、登录态、远端字幕、视频文件、驱动与模型可能变化。每次运行
   必须记录实际来源、尝试、工具版本、模型 revision、时间轴和原始产物，不能用旧案例替代
   当前探测。
3. **Agent 语义层**：证据选择、冲突判断、内容重构和视觉表达允许因任务而变，但必须保留
   claim—evidence—timestamp、用户授权的载体、作者口吻边界和忠实度审计。

因此，“任何 Agent 可复现”具体指：它能从仓库入口发现 Skill，在没有预注册 MCP 时用
JSON CLI 继续，按机器可读动作准备环境，只在真实人类边界停下，并产生可追溯、可校验的
结果。它不表示所有 Agent 客户端共享同一种 MCP 配置格式，也不表示 LLM 输出字节相同。

## 真值源

按以下顺序读取，不要维护第二套副本：

1. 根目录 `AGENTS.md`：任务路由、人机边界和全新机器入口；
2. `.agents/skills/*/SKILL.md`：字幕取证、内容转换和可选公众号草稿交接决策；
3. `src/video_subtitle/requirements.json`：能力依赖、已验证版本与模型 revision；
4. `requirements/runtime-lock.json`、`uv.lock`、Python constraints 与会随 npm 包发布的
   `npm-shrinkwrap.json`：重运行时和包解析基线；
5. `schemas/`：Bootstrap、setup、OCR 侦察、证据、内容、批次、迁移、渲染与微信回执契约；
6. `tests/fixtures/authorized-video/`：仓库自生成的 CC0 音视频和硬字幕离线夹具；
7. `tests/` 与 `scripts/repro_check.py`：确定性行为、入口可发现性和分层验收；
8. `docs/cases/`：观察性真实运行记录，不是可离线重放的测试 fixture。

## 干净 clone 验收

核心 Python 契约要求 Python 3.10 或更高版本。完整 Agent/Node 分发验收使用 Node.js 24；
`package.json` 支持 `^22.19 || >=24`，不要继续沿用无锁的 Node 20 假设。在仓库根目录执行：

```text
npx -y skills@1.5.22 add . --list
npm ci --ignore-scripts
python scripts/bootstrap.py --apply --config .video-subtitle-local/config.json --capability hard_ocr_local
```

验收 Bootstrap 返回的单份 JSON：

- `schema_version` 为 `video-subtitle/bootstrap-v2`；
- `installation.ready=true`；
- `installation.lock.verified=true`，并记录实际 constraints/lock SHA-256；
- `skills.available` 恰好包含 `video-subtitle`、`video-to-content` 与
  `wechat-draft-handoff`；
- `cli.command` 携带同一绝对配置路径；
- `mcp.transport=stdio`，且 `mcp.env.VIDEO_SUBTITLE_CONFIG` 指向同一配置；
- 缺少 VideOCR 时返回 Agent 动作，而不是虚假的 ready 或无关的人类动作。

随后由 Agent 处理当前任务所需的最小能力：

```text
<bootstrap 返回的 cli.command> setup --capability <capability>
<bootstrap 返回的 cli.command> doctor --capability <capability> --deep
<bootstrap 返回的 cli.command> ocr-scout-plan --duration-seconds 3600 --window-seconds 20
```

`setup` 未 ready 时是正常状态。Agent 应完成普通安装和路径持久化；浏览器登录、真实硬件
缺失、OS 权限确认，以及带 `confirmation_required=true` 的大体积下载才允许打断用户。

维护者的确定性验收为：

```text
python -m pip install -e ".[mcp,dev]"
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

CI 在 Windows 与 Ubuntu、Python 3.10 与 3.12 上运行完整测试；另有一个干净 Ubuntu
任务使用 Node.js 24 实际执行 npm 锁安装、浏览器适配器测试、打包内容检查、固定版本 Skill
discovery、Bootstrap apply，以及由 Bootstrap 创建的解释器执行 `core`/`agent` 分层复现检查。
macOS 尚未进入自动验收矩阵，不能只凭代码看起来可移植就宣称已经验证。

## 四层复现验收

`scripts/repro_check.py` 输出 `video-subtitle/repro-check-v1`，把“代码能跑”和“外部服务当前
可用”分开：

| 层级 | 自动检查 | 能证明什么 |
| --- | --- | --- |
| `core` | 锁文件、Skill 发现、CC0 媒体静态哈希、首方渲染与剪贴板、批次恢复、迁移包往返 | 确定性核心契约完整 |
| `agent` | Node 测试、stdio MCP 协议、稍后再看到草稿的确定性工作流、npm 打包内容 | 新 Agent 能发现入口，并证明任务与草稿幂等、失败关闭和禁止发布 |
| `media` | 用显式 FFprobe 或 FFmpeg 解码夹具的视频流和音轨 | 当前媒体工具可读取授权夹具 |
| `live` | 始终为 `manual_required` | 提醒必须另做登录、真实 OCR/ASR 和微信交接 |

`agent` tier 的 `watch_later_to_draft_contract` 使用
`tests/fixtures/automation/`，不访问任何真实账号。它验证一个新增条目只创建一个任务，
多源证据生成 canonical subtitle，文章通过审计后只绑定一份草稿；第二周期不重复任务或草稿；
不可用证据以 `unprocessable` 在内容阶段前结束；原始证据哈希不变；回执始终记录
`published=false`。这能证明持久契约和幂等性，不能证明当前 Browser Bridge 或微信登录有效。

完整运行和 live acceptance 边界见
[`watch-later-automation.md`](watch-later-automation.md)。

完整离线验收示例：

```powershell
python scripts/repro_check.py `
  --require-tier core `
  --require-tier agent `
  --require-tier media `
  --ffmpeg C:\path\to\ffmpeg.exe `
  --output .\repro-report.json
```

`core` 通过不代表 VideOCR 模型真的在当前 GPU 上运行；`media` 通过也只证明 FFmpeg 能解码
仓库夹具；`live` 不允许用 mock、旧案例或成功 HTTP 状态冒充完成。LLM 文章只承诺契约等价和
证据可追溯，不承诺字节级一致。

## 真实媒体验收边界

登录 Bilibili、下载受版权约束的视频、运行 GPU OCR/ASR 和下载大模型不适合放进公共 CI：
它们需要用户会话、硬件、网络成本和内容授权。真实验收应选择用户有权处理的样本，完成：

1. setup/deep doctor；
2. 解析元数据和平台字幕；不论平台字幕是否存在，都独立判断连续硬字幕，必要时先生成并执行
   稀疏 OCR 侦察窗口；
3. 侦察确认存在连续硬字幕时执行全片 OCR；只有确认不存在时才跳过；
4. 平台字幕、OCR、ASR 独立落盘；
5. manifest、attempt、日志与 SHA-256 保留；下载 attempt 的缓存、重试和 `actual_bytes` 与
   实际文件一致；
6. 按时间范围读取并核对冲突；
7. 用户指定载体后再建立 content map、media plan、成品和 fidelity audit，并用显式阶段计时
   记录 Agent、工具、人类等待和外部交接耗时；
8. 公众号文章包先运行 `scripts/validate_wechat_package.py`，确认图片标记、清单、本地文件、
   正式 HTML 和预览文案满足确定性交付契约；
9. 公众号语义稿先通过首方 `scripts/render_wechat_article.py` 生成并校验；若选择其他渲染器，
   仍须满足相同的原视频配图、单行路径、无下划线/CTA/签名和干净 HTML 边界；
10. 仅当用户明确要求公众号草稿交接时，另行验证已登录编辑器、临时剪贴板图片运输、微信
   CDN 接管、元数据和草稿保存状态；生成 `video-content/wechat-draft-receipt-v1`，使用
   `scripts/build_wechat_draft_receipt.py` 从无秘密浏览器观察构建并验证，并明确没有发布。

`docs/cases/` 只证明某个日期、某台机器和某组上游输入曾真实跑通。远端视频可能删除或
改版，仓库也不分发原视频、模型或登录凭证，因此这些文档不能冒充一键 replay fixture。
多视频验收也不能把队列汇总当成单个可复现产物：`video-content/batch-v1` 只记录每条视频的
subtitle/content/handoff 阶段、尝试、恢复点和批次内产物路径。每条视频必须有独立 manifest、
content project、当前审计和可选草稿回执。下载缓存可以共享，但缓存命中必须由缓存键、文件
存在和真实大小共同证明。

首方 `restrained-editorial` 渲染器属于确定性仓库工具；可选第三方渲染器和
`wechat-draft-handoff` 属于可替换表现/外部执行层。真实案例应记录渲染器版本或 commit、主题、
确定性校验结果、本地图片交接方式，以及平台交接实际验证到的图片数量、CDN 接管和保存状态；
新运行仍应重新检查当前 Skill 与页面。即使富文本剪贴板或已登录浏览器不可用，content map、
media plan、文章语义稿、首方干净 HTML、人工图片清单和 fidelity audit 也必须能独立完成。

跨机器交接使用 `scripts/project_bundle.py export` 生成
`video-content/portable-bundle-v1` ZIP，再在目标机器先 `verify` 后 `import`。包内每个文件带
SHA-256；导出拒绝 Cookie/Token/密码痕迹和持久化 Base64，导入拒绝路径穿越，默认排除大体积
原视频。这个包迁移项目证据和产物，不迁移登录态、模型、外部工具或旧机器 GPU 并行结论。

## 升级纪律

- 工具或模型升级必须更新 `requirements.json` 的 `verified_at` 与对应 version/revision；
- 重运行时升级必须同步更新 `runtime-lock.json` 的资产字节数、SHA-256、包组合或模型 revision；
- Python 或 Node 依赖变化必须重建相应锁文件并确认 Bootstrap/打包报告的哈希；
- 不把“latest”静默混入声称可复现的任务；
- 模型目录必须对应记录的 revision，大下载仍需事前确认；
- 升级后先跑 schema、单元测试、MCP smoke 和干净 clone，再用代表性真实样本验证；
- 新增向后兼容能力时同步更新 `pyproject.toml` 与 `video_subtitle.__version__`，并通过测试防止漂移；
- 新机器或驱动变化后恢复 `media_execution=auto`，不得继承旧机器的并行结论。

## 当前明确限制

- 平台适配目前只有 Bilibili；YouTube 与抖音尚未实现；
- 批次台账不执行调度，也不合并多个 manifest 或内容项目；Agent 仍负责选择逐条顺序和并发；
- MCP 注册由调用 Agent 完成，仓库只提供可移植的 stdio 参数与 CLI fallback；
- 自动登录、正式发布、定时、群发、原创声明和账号管理不属于项目职责；可选
  `wechat-draft-handoff` 只在用户明确要求时复用已经登录的可见浏览器并保存草稿；
- 首方公众号渲染器只实现克制编辑基线，不替代 Agent 写作、视觉选材或忠实度审计；第三方主题
  仍是可选下游能力，不由 `requirements.json` 安装；
- 没有外部真值集时不报告 OCR/ASR 的虚构准确率；
- 外部事实核验是独立工作，字幕多源一致不等于事实为真。

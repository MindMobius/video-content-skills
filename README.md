# Video Subtitle Skill

一套让 Agent 按需获取、读取和核验视频字幕证据，并把已核验内容转换为合适媒介的
Skill、MCP Server 与 JSON CLI。

它不会把平台字幕、硬字幕 OCR 或音频 ASR 自动拼成“唯一正确稿”。工具负责依赖
检查、登录态、下载、识别、时间轴和产物；Agent 负责选择证据、理解语义、判断冲突
并决定是否继续取证。

仓库包含两个相互解耦的 Skill：`video-subtitle` 负责建立证据，`video-to-content` 负责
把证据重建为可追溯的内容模型，再按用户指定的文章、一图流、卡片、Brief 或口播稿等
载体生成成品。用户没有指定载体时，Agent 可以分析和推荐，但必须等待用户选择；只有用户
明确委托时才能代选。语义判断始终由 Agent 完成，工具只做依赖、持久化、版本和确定性校验。

项目的终点是忠实、得体、恰当、优雅且通过审计的可交付成品。登录发布平台、上传文件、
写入草稿箱、定时发布和账号管理均不属于本项目职责。

## Agent 快速入口

仓库内的两个 Skill 位于标准项目目录 [`.agents/skills`](.agents/skills)，支持该约定的
Agent 在进入仓库后可以直接发现。其他项目或个人环境可先检查再安装：

```powershell
npx skills add MindMobius/video-subtitle-skill --list
npx skills add MindMobius/video-subtitle-skill `
  --skill video-subtitle `
  --skill video-to-content
```

不支持 Agent Skills 自动发现的 Coding Agent 应从 [`AGENTS.md`](AGENTS.md) 开始；它会
把任务路由到对应 Skill，并给出全新机器的 bootstrap、依赖检查、人机边界和验证规则。
Skill 负责告诉 Agent 如何判断和使用工具，不会假设 MCP 已经注册；MCP 不可用时使用同契约
的 JSON CLI。可验证范围、干净 clone 验收和非确定性边界见
[`docs/reproducibility.md`](docs/reproducibility.md)。

## 当前能力

- Bilibili 普通链接、短链接和分 P；
- OpenCLI Browser Bridge 登录态与平台字幕；
- 本地视频或下载视频的 VideOCR 硬字幕时间轴；
- Qwen3-ASR 与 Forced Aligner 音频时间轴；
- OCR 与 ASR 独立执行、按机器资源安全调度；
- 按来源、按任意时间范围读取字幕证据；
- 可选的固定窗口精校与不可变原始产物；
- 面向 Agent 的依赖检查、配置持久化和修复动作。
- 固定字幕 manifest 与各路证据哈希的内容工程项目；
- 与媒介无关的 content map，以及 claim—evidence—timestamp 引用；
- 用户授权的载体决策，以及由 Agent 完成的重构策略、叙述口吻、版本化成品和逐项忠实度审计；
- 检测证据变化、过期媒介计划、未审计成品和缺失核心限定条件。

YouTube 与抖音平台适配器尚未实现。OCR、ASR、证据和审阅核心不依赖平台，新增
平台只需实现 [`platforms/base.py`](src/video_subtitle/platforms/base.py) 的最小接口。

## Agent 可迁移环境

Python 包依赖写在 `pyproject.toml`；外部程序、模型、浏览器登录态和硬件依赖写在
机器可读的 [`requirements.json`](src/video_subtitle/requirements.json)。后者按能力
声明依赖，并把修复动作严格分为：

- `agent_actions`：Agent 应自行定位、安装或配置；
- `human_actions`：浏览器登录、硬件缺失等必须由人处理的边界；
- `confirmation_required`：模型等大体积下载，Agent 执行前需要确认成本。

`requirements.json` 还记录 `verified_at`、已验证工具版本和模型 revision。它们是当前
可复现基线，不是“永远使用旧版本”的锁死策略；升级时应先更新版本或 revision、完成
schema 与回归测试，再改写基线，不能在同一次任务中静默漂移。

Agent 应只请求当前任务需要的能力；setup/doctor 也只运行相应 probe，不会为本地
OCR 无故检查浏览器登录或导入 ASR/CUDA。

在一台新机器上，从仓库根目录开始：

```powershell
# 只检查基础安装，不修改环境
python scripts\bootstrap.py

# 创建 .venv、安装 MCP 支持，并检查当前任务所需能力
python scripts\bootstrap.py --apply `
  --config .\.video-subtitle-local\config.json `
  --capability platform_subtitle `
  --capability hard_ocr_url
```

Bootstrap 始终只向 stdout 输出一份 `video-subtitle/bootstrap-v2` JSON。除了安装状态，
它还给出规范 Skill 路径、可直接执行的 JSON CLI 命令、stdio MCP 启动参数，以及嵌套的
setup 结果。MCP 的注册方式由调用它的 Agent 决定；尚未注册时，直接使用返回的 CLI
命令即可继续同一契约。干净 clone、CI 或可复现实验应显式传入 `--config`，避免继承宿主机
默认配置。

安装完成后遵循同一个闭环：

```powershell
# 快速检查并返回精确的 Agent / human actions
video-subtitle --config .\.video-subtitle-local\config.json setup `
  --capability platform_subtitle `
  --capability hard_ocr_url

# 将 Agent 找到的非秘密路径和 Browser Bridge profile 持久化
video-subtitle --config .\.video-subtitle-local\config.json configure `
  --opencli opencli `
  --profile browser-bridge-profile `
  --ytdlp C:\path\to\yt-dlp.exe `
  --ffmpeg C:\path\to\ffmpeg.exe `
  --videocr C:\path\to\videocr-cli.exe

# setup ready 后做真实运行时检查；ASR 会验证 CUDA 与显存
video-subtitle --config .\.video-subtitle-local\config.json doctor --capability hard_ocr_url
video-subtitle --config .\.video-subtitle-local\config.json doctor --capability audio_asr_url
```

默认配置位置：

- Windows：`%APPDATA%\video-subtitle\config.json`
- Linux/macOS：`$XDG_CONFIG_HOME/video-subtitle/config.json`，未设置时使用
  `~/.config/video-subtitle/config.json`

解析优先级为：命令行参数 > 环境变量 > 持久配置 > `PATH`。配置只保存路径、
profile 别名、任务目录和执行策略，不保存 cookie、密码或 token。完整说明见
[`docs/environment.md`](docs/environment.md)。
完整的可复现定义、跨平台 CI 和真实媒体验收边界见
[`docs/reproducibility.md`](docs/reproducibility.md)。

Bootstrap、依赖清单、持久配置和 setup 响应分别由
[`bootstrap.schema.json`](schemas/bootstrap.schema.json)、
[`requirements.schema.json`](schemas/requirements.schema.json)、
[`config.schema.json`](schemas/config.schema.json) 和
[`setup.schema.json`](schemas/setup.schema.json) 校验，避免文档、工具输出和测试各自漂移。
内容工程的项目、内容地图、媒介计划和忠实度审计分别由
[`content-project.schema.json`](schemas/content-project.schema.json)、
[`content-map.schema.json`](schemas/content-map.schema.json)、
[`media-plan.schema.json`](schemas/media-plan.schema.json) 和
[`fidelity-audit.schema.json`](schemas/fidelity-audit.schema.json) 定义。

## 使用流程

默认主证据顺序为：

```text
platform subtitle > hard OCR > audio ASR
```

这只是快速消费的默认顺序，不是准确率排名：

1. 先查询便宜的平台字幕；
2. 平台没有字幕时，硬字幕视频以 OCR 为主来源；
3. 无硬字幕时以 ASR 兜底；
4. 高价值、外语或术语密集内容可同时保留 OCR 与 ASR，交给 Agent 按时间和语义
   核验；
5. 已知冲突优先局部重跑，不因一个词重新处理全片。

多来源任务以 `fusion_status=independent_evidence` 完成。这表示证据已齐，不表示
工具替 Agent 做完了语义裁决。

## OCR / ASR 调度

OCR 与 ASR 使用同一份本地视频，但写入不同产物，完成后按确定顺序合并 manifest：

- `auto`：GPU OCR 与 Qwen3-ASR 共用显卡时串行；资源独立时并行；
- `serial`：始终串行，适合未知或紧张的机器资源；
- `parallel`：显式并行，只应在 deep doctor 和本机实测通过后启用。

```powershell
video-subtitle extract $url `
  --output .\result `
  --collect-all-sources `
  --ocr-backend videocr `
  --ocr-gpu `
  --ocr-consensus-image-max-width 600 `
  --asr-backend qwen3 `
  --media-execution auto
```

在当前开发机上，16 分 08 秒的真实 Bilibili 视频显式并行用时 165 秒，原串行用时
251 秒，缩短约 34%；两次均生成 15 份产物且无告警。这只是一次主机级验证，不能
外推为其他显卡的性能或稳定性保证。详见
[`BV1KHNC61ExM 实测`](docs/cases/BV1KHNC61ExM.md)。

同一台机器对另一条双尺度 OCR 视频的结果相反：并行争抢 GPU 时 ASR 第一段曾用时
470 秒，串行时为 35 秒。并行结论也不能跨 OCR 分辨率、共识轮次和视频形态外推；详见
[`BV1v6Kf6rEYh 一图流实测`](docs/cases/BV1v6Kf6rEYh-one-page.md)。

## CLI

所有命令只向 stdout 输出 JSON。

```powershell
video-subtitle inspect "https://www.bilibili.com/video/BV..."

# 同步采集
video-subtitle extract $url --output .\result

# 耗时任务使用后台 job
video-subtitle --home .\.video-subtitle start $url
video-subtitle --home .\.video-subtitle status <job-id>
```

Agent 先列举证据，再读取需要的来源与时间范围：

```powershell
video-subtitle evidence-list --manifest .\result\manifest.json
video-subtitle evidence-read `
  --manifest .\result\manifest.json `
  --evidence-id ev-0002 `
  --start-ms 360000 `
  --end-ms 390000
```

需要交付完整精校 SRT 时再启用可选审阅助手：

```powershell
video-subtitle review-prepare --manifest .\result\manifest.json
video-subtitle review-window --manifest .\result\manifest.json
video-subtitle review-apply `
  --manifest .\result\manifest.json `
  --decisions .\review-decisions.json
```

将已完成的字幕证据继续转换为其他内容媒介：

```powershell
video-subtitle content-init --manifest .\result\manifest.json
video-subtitle content-save --project .\result\content\<project-id>\project.json `
  --kind content_map --document .\content-map.json
video-subtitle content-save --project .\result\content\<project-id>\project.json `
  --kind media_plan --document .\media-plan.json
video-subtitle content-deliverable `
  --project .\result\content\<project-id>\project.json `
  --medium article --format markdown --content-file .\article.md `
  --title "文章标题" --used-claim-id claim-0001
video-subtitle content-save --project .\result\content\<project-id>\project.json `
  --kind fidelity_audit --document .\fidelity-audit.json
video-subtitle content-validate `
  --project .\result\content\<project-id>\project.json
```

完整工作流、状态失效规则和 dbskill 复用边界见
[`docs/content-workflow.md`](docs/content-workflow.md)。
真实的 16 分钟视频全链路结果见
[`BV1KHNC61ExM 内容转换实测`](docs/cases/BV1KHNC61ExM-content.md)。
按载体重构、使用联合作者口吻并输出 SVG/PNG 一图流的结果见
[`BV1v6Kf6rEYh 一图流实测`](docs/cases/BV1v6Kf6rEYh-one-page.md)。

## MCP

MCP Server 使用 stdio，共暴露 18 个工具：

环境：

- `video_subtitle_setup`
- `configure_video_subtitle`
- `video_subtitle_doctor`

采集：

- `inspect_bilibili_video`
- `start_subtitle_extraction`
- `get_subtitle_job`

证据：

- `list_subtitle_evidence`
- `read_subtitle_evidence`
- `read_subtitle_artifact`

可选精校：

- `prepare_subtitle_review`
- `get_subtitle_review_window`
- `submit_subtitle_review_window`

内容工程：

- `initialize_video_content`
- `get_video_content_project`
- `save_video_content_document`
- `save_video_content_deliverable`
- `read_video_content_artifact`
- `validate_video_content_project`

Codex 配置示例：

```toml
[mcp_servers.video_subtitle]
command = "C:\\path\\to\\video-subtitle-skill\\.venv\\Scripts\\python.exe"
args = ["-m", "video_subtitle.mcp_server"]
env = { VIDEO_SUBTITLE_CONFIG = "C:\\path\\to\\config.json" }
```

环境路径已经由 `configure_video_subtitle` 持久化时，MCP 配置无需重复书写。若要
覆盖，仍可在 MCP `env` 中传入相同的 `VIDEO_SUBTITLE_*` 环境变量。

## 证据边界

- 平台字幕、OCR、ASR 始终保留为独立证据；
- 双尺度 OCR 一致只说明两种图像尺度读到了同样文字，不证明视频硬字幕本身正确；
- ASR 能发现 OCR 漏句和疑似错字，但不能独自证明同音人名、数字、符号和术语写法；
- 外语音频与中文字幕按重叠时间和语义核对，不按字符相似度核对；
- 原始字幕产物不可修改，修订必须创建带来源、理由和时间戳的派生产物；
- 没有独立真值集时，不报告虚构的“准确率”。

每个任务以 `manifest.json` 为入口，包含来源、尝试、调度决策、告警和产物目录。
典型产物包括 `subtitle.platform.*`、`subtitle.ocr.*`、`subtitle.asr.*`、
`evidence.index.*`、进程日志和可选的 `subtitle.reviewed.*`。

## 目录结构

```text
video-subtitle-skill/
├─ AGENTS.md                          通用 Agent 发现、路由与环境入口
├─ .agents/skills/video-subtitle/     字幕证据决策与安全边界
├─ .agents/skills/video-to-content/   内容重建、载体决策门、生成与审计 Prompt
├─ src/video_subtitle/
│  ├─ requirements.json               外部能力依赖契约
│  ├─ config.py                       持久配置与优先级
│  ├─ environment.py                  setup 动作规划
│  ├─ diagnostics.py                  quick/deep doctor
│  ├─ platforms/                      平台适配器
│  ├─ backends/                       OCR、ASR、Forced Aligner
│  ├─ core/                           SRT、证据、派生审阅与内容工程
│  ├─ pipeline.py                     采集和资源调度
│  ├─ jobs.py                         持久后台任务
│  ├─ cli.py
│  └─ mcp_server.py
├─ scripts/bootstrap.py                无依赖安装入口与 Agent 运行契约
├─ schemas/                            Bootstrap、环境、证据与内容契约
├─ tests/
└─ docs/reproducibility.md             干净 clone、CI 与真实媒体验收边界
```

## 开发验证

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts\mcp_smoke.py
```

当前优先级是用真实长视频验证 content map 与媒介路由、增加按范围抽帧和可选渲染器，
以及局部 OCR/ASR、通用派生修订、YouTube 和抖音平台适配器，而不是继续扩大固定启发式
审阅或摘要规则。

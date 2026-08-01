# Video Subtitle Skill

一套供模型按需获取和核验视频字幕证据的 Skill、MCP Server 与 JSON CLI。

它不会把平台字幕、硬字幕 OCR 或音频 ASR 自动包装成唯一真相。工具负责可靠地
取得证据、处理时间轴并保存产物；调用方负责决定读取哪个来源、检查哪个时间段、
是否需要补充证据。

## 当前支持范围

- Bilibili 普通链接、短链接和分 P：通过 OpenCLI 与 Browser Bridge 登录态；
- Bilibili 平台字幕；
- 本地视频或下载视频的硬字幕 OCR；
- Qwen3-ASR 与 Forced Aligner 音频时间轴；
- 按来源、按任意时间范围读取字幕；
- 可选的固定窗口审阅和派生字幕。

YouTube 与抖音适配器尚未实现。核心 OCR、ASR、证据和审阅模块不依赖平台，新增
平台只需实现 `platforms/base.py` 定义的接口。

## 设计边界

```text
Skill / MCP / CLI
        │
        ├─ platforms/    链接、登录态、平台字幕、视频下载
        ├─ backends/     OCR、ASR、Forced Aligner
        ├─ core/         SRT、证据读取、审阅、派生产物
        └─ pipeline.py   采集编排与 manifest
```

默认主证据顺序为：

```text
platform subtitle > hard OCR > audio ASR
```

这只是快速消费的默认值。多来源任务以
`fusion_status=independent_evidence` 完成，由调用方自行选择证据。固定 30 秒审阅包
不再自动生成，只在完整精校确实有价值时显式使用。

## 目录结构

```text
video-subtitle-skill/
├─ skills/video-subtitle/SKILL.md
├─ src/video_subtitle/
│  ├─ platforms/
│  │  ├─ base.py
│  │  └─ bilibili.py
│  ├─ backends/
│  │  ├─ ocr.py
│  │  ├─ asr.py
│  │  └─ qwen_asr_worker.py
│  ├─ core/
│  │  ├─ evidence.py
│  │  ├─ review.py
│  │  ├─ srt.py
│  │  └─ util.py
│  ├─ pipeline.py
│  ├─ jobs.py
│  ├─ cli.py
│  └─ mcp_server.py
├─ schemas/
├─ tests/
└─ docs/
```

## 安装

需要 Python 3.10+。Bilibili 平台能力还需要已经构建的 OpenCLI，以及 Chrome 中
连接成功的 OpenCLI Browser Bridge。OCR/ASR 能力按需安装。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp,dev]"
```

环境变量示例：

```powershell
$env:VIDEO_SUBTITLE_OPENCLI = "C:\path\to\OpenCLI\dist\src\main.js"
$env:VIDEO_SUBTITLE_OPENCLI_PROFILE = "browser-bridge-profile"
$env:VIDEO_SUBTITLE_YTDLP = "C:\path\to\yt-dlp.exe"
$env:VIDEO_SUBTITLE_FFMPEG = "C:\path\to\ffmpeg.exe"
$env:VIDEO_SUBTITLE_VIDEOCR = "C:\path\to\videocr-cli.exe"
$env:VIDEO_SUBTITLE_ASR_PYTHON = "C:\path\to\asr-env\Scripts\python.exe"
$env:VIDEO_SUBTITLE_QWEN_ASR_MODEL = "C:\path\to\Qwen3-ASR-1.7B"
$env:VIDEO_SUBTITLE_QWEN_ALIGNER_MODEL = "C:\path\to\Qwen3-ForcedAligner-0.6B"
```

## CLI

所有命令只向 stdout 输出 JSON。

```powershell
video-subtitle doctor
video-subtitle inspect "https://www.bilibili.com/video/BV..."

# 同步采集
video-subtitle extract $url --output .\result

# 后台任务
video-subtitle --home .\.video-subtitle start $url
video-subtitle --home .\.video-subtitle status <job-id>
```

高价值视频可以收集 OCR 与 ASR 两路证据：

```powershell
video-subtitle extract $url `
  --output .\result `
  --collect-all-sources `
  --ocr-backend videocr `
  --ocr-consensus-image-max-width 600 `
  --asr-backend qwen3 `
  --asr-language auto
```

调用方先列举证据，再读取需要的时间段：

```powershell
video-subtitle evidence-list --manifest .\result\manifest.json
video-subtitle evidence-read `
  --manifest .\result\manifest.json `
  --evidence-id ev-0002 `
  --start-ms 360000 `
  --end-ms 390000
```

需要完整精校时再启用可选审阅助手：

```powershell
video-subtitle review-prepare --manifest .\result\manifest.json
video-subtitle review-window --manifest .\result\manifest.json
video-subtitle review-apply `
  --manifest .\result\manifest.json `
  --decisions .\review-decisions.json
```

## MCP

MCP Server 使用 stdio，暴露十个工具：

- `video_subtitle_doctor`
- `inspect_bilibili_video`
- `start_subtitle_extraction`
- `get_subtitle_job`
- `list_subtitle_evidence`
- `read_subtitle_evidence`
- `prepare_subtitle_review`
- `get_subtitle_review_window`
- `submit_subtitle_review_window`
- `read_subtitle_artifact`

Codex 配置示例：

```toml
[mcp_servers.video_subtitle]
command = "C:\\path\\to\\video-subtitle-skill\\.venv\\Scripts\\python.exe"
args = ["-m", "video_subtitle.mcp_server"]

[mcp_servers.video_subtitle.env]
VIDEO_SUBTITLE_OPENCLI = "C:\\path\\to\\OpenCLI\\dist\\src\\main.js"
VIDEO_SUBTITLE_OPENCLI_PROFILE = "browser-bridge-profile"
VIDEO_SUBTITLE_HOME = "C:\\path\\to\\video-subtitle-data"
```

## 产物

每个任务以 `manifest.json` 为入口，并按实际执行情况生成：

- `subtitle.platform.*`：平台字幕；
- `subtitle.ocr.*`：硬字幕 OCR；
- `subtitle.ocr.primary.srt` / `subtitle.ocr.validation.srt`：双尺度原始证据；
- `subtitle.asr.*`：ASR 与时间戳；
- `evidence.index.*`：独立证据目录；
- `review.*` / `subtitle.reviewed.*`：仅在使用可选审阅助手时生成；
- `ocr.log` / `asr.log`：执行日志。

原始字幕产物不可修改。所有修订必须创建派生产物并保留来源、理由和时间戳。

## Skill 与协议

Skill 位于 [`skills/video-subtitle/SKILL.md`](skills/video-subtitle/SKILL.md)。机器
可读协议位于 [`schemas/`](schemas/)，完整执行边界见
[`docs/workflow.md`](docs/workflow.md)。

## 验证

```powershell
python -m ruff check .
python -m pytest
python scripts\mcp_smoke.py
```

现阶段优先补充按范围抽帧、局部 OCR/ASR、通用派生修订，以及 YouTube、抖音
平台适配器，而不是继续扩大固定启发式审阅规则。

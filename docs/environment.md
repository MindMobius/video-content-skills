# Agent 环境契约

## 目标

这个 Skill 不能假设目标机器已经安装 OpenCLI、VideOCR、CUDA 模型或正确的浏览器
登录态。环境准备必须成为可观察、可恢复、可持久化的 Agent 工作，而不是 README
里一组只能由人照抄的安装命令。

环境闭环由四层组成：

```text
scripts/bootstrap.py
  → 安装 Python 包与 MCP 入口
video_subtitle_setup
  → 按能力解析外部依赖，返回 Agent / human actions
configure_video_subtitle
  → 持久化已发现的非秘密配置
video_subtitle_doctor
  → 验证实际登录态、进程、CUDA 与显存
```

## 两类依赖清单

`pyproject.toml` 是标准 Python 包依赖真值源。打包在
`src/video_subtitle/requirements.json` 中的 `video-subtitle/requirements-v1`
描述 Python 之外的运行能力：

- 可执行程序：Node.js、yt-dlp、FFmpeg；
- 外部项目或二进制：OpenCLI、VideOCR；
- 独立 Python 环境：CUDA PyTorch 与 Qwen3-ASR；
- 大模型：Qwen3-ASR 与 Forced Aligner；
- 人类会话：OpenCLI Browser Bridge 与 Bilibili 登录；
- 硬件运行时：NVIDIA GPU 与 CUDA。

每项能力只引用自己真正需要的依赖。Agent 应请求最小能力集合，不应默认安装全部
模型和后端。

## 能力矩阵

| 能力 | 用途 | 关键依赖 |
| --- | --- | --- |
| `platform_subtitle` | Bilibili 元数据和平台字幕 | Python、Node、OpenCLI、Browser Bridge |
| `video_download` | 获取一次认证视频 | 平台能力、yt-dlp、FFmpeg |
| `hard_ocr_local` | 对本地视频做硬字幕 OCR | Python、VideOCR |
| `hard_ocr_url` | 下载后做硬字幕 OCR | 下载能力、VideOCR |
| `audio_asr_local` | 对本地视频做 Qwen3-ASR | FFmpeg、ASR 环境、两个模型、CUDA |
| `audio_asr_url` | 下载后做 Qwen3-ASR | 下载能力、ASR 环境、两个模型、CUDA |

## setup 状态机

`video_subtitle_setup` 返回 `video-subtitle/setup-v1`：

```text
agent_action_required
  → Agent 执行安装、定位或配置动作
  → configure 持久化结果
  → 重跑 setup

human_action_required
  → Agent 先完成仍可执行的 agent_actions
  → 只向人请求 human_actions
  → configure 持久化 profile 等结果
  → 重跑 setup

ready
  → deep doctor
  → 开始任务
```

依赖被上游缺失项阻塞时标记为 `blocked`。例如 OpenCLI 尚未安装时，Browser Bridge
不是立刻要求人处理，而是先让 Agent 安装 OpenCLI；安装完成后重新检查，才可能出现
真实的登录动作。

`confirmation_required=true` 仍属于 Agent 动作，但涉及较大网络或磁盘成本。Agent
应先报告模型和动作，再取得确认，不能把整项安装劳动转交给用户。

## 可持久化配置

`video-subtitle/config-v1` 可以保存：

- `opencli`
- `opencli_profile`
- `ytdlp`
- `ffmpeg`
- `videocr`
- `asr_python`
- `qwen_asr_model`
- `qwen_aligner_model`
- `home`
- `media_execution`

配置不包含 cookie、密码或 token。Browser Bridge profile 只是连接别名，真实登录态
仍留在用户浏览器中。

默认位置：

- Windows：`%APPDATA%\video-subtitle\config.json`
- XDG：`$XDG_CONFIG_HOME/video-subtitle/config.json`
- 其他：`~/.config/video-subtitle/config.json`

可用 `--config` 或 `VIDEO_SUBTITLE_CONFIG` 指向另一份文件。解析优先级是：

```text
CLI 参数 > 环境变量 > 配置文件 > PATH
```

环境变量覆盖配置文件，适合 CI、临时测试和多实例 MCP；配置文件适合个人工作站的
稳定迁移。

## quick 与 deep doctor

快速 setup/doctor 只检查路径、命令和配置，不导入大型 CUDA 模型，适合每次任务前
低成本预检。

诊断器只运行 requested capabilities 需要的 probe：本地 OCR 不检查 Browser Bridge、
下载器或 ASR；平台字幕不导入 CUDA；本地 ASR 只额外检查其必需的 FFmpeg。这样能力
拆分不仅控制安装范围，也控制每次预检的时间和副作用。

deep doctor 会进入独立 ASR Python 环境，验证：

- `torch` 与 `qwen_asr` 可以导入；
- CUDA 对该环境可见；
- GPU 型号和总显存可读取；
- OpenCLI Browser Bridge 当前仍连接并登录 Bilibili。

路径存在不等于运行时可用。因此涉及 ASR、驱动变化、机器迁移或显式并行时，必须
做 deep doctor。

## 资源调度

`media_execution=auto` 根据当前请求而不是机器名决策：

- 只有一路媒体后端：串行；
- CPU VideOCR 与 GPU ASR：并行；
- GPU VideOCR 与 GPU ASR：串行，防止未知显存机器 OOM；
- 用户显式选择 `parallel`：并行，并在 manifest 中记为显式决策。

只有 deep doctor 和有代表性的真实样本都证明并发稳定且更快后，Agent 才应持久化
`parallel`。显存足够只能证明两路进程可能同时容纳，不能证明吞吐更高；样本还应覆盖实际
使用的 OCR 分辨率、双尺度共识、视频画面形态和 ASR 参数。
迁移配置到另一台机器时，应恢复 `auto` 并重新验证。

## Agent 执行规则

1. 不猜测依赖状态，先调用 setup。
2. 不把普通安装命令甩给用户，先完成 `agent_actions`。
3. 不请求 cookie；只请求浏览器登录和 profile alias。
4. 不在未确认时下载大模型。
5. 不因 ASR 未配置而阻塞只需要平台字幕或 OCR 的任务。
6. 每次配置后重跑 setup，避免把“写入路径”误当作“能力已就绪”。
7. 只有 requested capabilities 全部 ready 才进入提取。
8. 失败时保留 setup、doctor、manifest 和日志作为下一轮诊断证据。

## 扩展契约

新增外部依赖时：

1. 在 `requirements.json` 的 `dependencies` 中定义唯一 ID、类型、描述和动作；
2. 只把它加入真正需要的 capability；
3. 在诊断层返回 `ready`、`missing`、`blocked` 或
   `human_action_required`；
4. 若有配置字段，同时加入 config 映射和配置 schema；
5. 为 Agent/human 分流、配置优先级和缺失上游项添加测试；
6. 更新 Skill，而不是把不可判断的语义决策写进安装脚本。

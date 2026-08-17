# Agent 环境契约

> **阅读时机**：新机器准备、能力缺失、重运行时安装或 doctor 诊断时阅读。具体任务仍由命中的 Skill 决定需要哪些能力。

## 目标

这个 Skill 不能假设目标机器已经安装 OpenCLI、VideOCR、CUDA 模型或正确的浏览器
登录态。环境准备必须成为可观察、可恢复、可持久化的 Agent 工作，而不是 README
里一组只能由人照抄的安装命令。

环境闭环由四层组成：

```text
scripts/bootstrap.py
  → 按 Python 约束安装包，报告 Skill、CLI、MCP 入口、锁哈希与 setup 结果
video_subtitle_setup
  → 按能力解析外部依赖，返回 Agent / human actions
scripts/runtime_setup.py
  → 按重运行时锁计划、确认安装并校验 FFmpeg、VideOCR、ASR 与模型
configure_video_subtitle
  → 持久化已发现的非秘密配置
video_subtitle_doctor
  → 验证实际登录态、进程、CUDA 与显存
```

Bootstrap 返回一份由 `schemas/bootstrap.schema.json` 约束的
`video-subtitle/bootstrap-v2` JSON；pip 和子进程日志不会混入 stdout。调用方可据此：

1. 从 `skills.available` 找到规范 Skill；
2. 直接执行 `cli.command`，或按 `mcp` 注册 stdio 服务；
3. 继续处理 `setup.agent_actions` 与 `setup.human_actions`；
4. 在 CI、干净 clone 和验收时用 `--config <隔离路径>` 排除宿主机默认配置。

MCP 客户端的配置格式各不相同，因此 Bootstrap 报告可移植的 `command`、`args` 和
`transport`，不直接改写任一 Agent 的全局配置。MCP 不可用时，`fallback_command` 指向
同一份 JSON CLI 契约。

## 四类依赖真值源

1. `pyproject.toml` 定义 Python 包的直接依赖与可选组；`uv.lock` 和
   `requirements/mcp-constraints.txt` 固定已验证解析结果。
2. `package.json` 定义 DSH/Node 分发边界；`npm-shrinkwrap.json` 固定 npm 开发契约并随
   发布包分发。
3. `src/video_subtitle/requirements.json` 的
   `video-subtitle/requirements-v1` 描述每项能力需要哪些外部依赖，以及 Agent、人类和确认
   动作如何分流。
4. `requirements/runtime-lock.json` 的 `video-subtitle/runtime-lock-v1` 固定大体积或独立
   运行时：VideOCR 1.5.1 的平台资产、字节数与 SHA-256，ASR Python/包组合，以及两个模型
   的 40 位 revision。

能力依赖包括：

- 可执行程序：Node.js、yt-dlp、FFmpeg；
- 外部项目或二进制：OpenCLI、VideOCR；
- 独立 Python 环境：CUDA PyTorch 与 Qwen3-ASR；
- 大模型：Qwen3-ASR 与 Forced Aligner；
- 人类会话：OpenCLI Browser Bridge 与 Bilibili 登录；
- 硬件运行时：NVIDIA GPU 与 CUDA。

每项能力只引用自己真正需要的依赖。Agent 应请求最小能力集合，不应默认安装全部
模型和后端。

两份 JSON 清单的 `verified_at` 记录基线核验日期；能力依赖可带 `tested_version` 或
`tested_revision`。这是可复现实验和故障回退使用的已验证组合，不代表永不升级。升级者应
查验上游来源，明确改动版本、资产哈希或模型 revision，并让 schema、单元测试、锁文件和分层
复现验收同时通过。不能把无版本的“安装最新版”当作可复现安装动作。

## 重运行时计划与确认

`scripts/runtime_setup.py` 始终输出 `video-subtitle/runtime-action-v1` JSON，并附带当前
runtime lock 的绝对路径、SHA-256 和 `verified_at`。先运行只读计划：

```powershell
python scripts/runtime_setup.py plan ffmpeg
python scripts/runtime_setup.py plan videocr
python scripts/runtime_setup.py plan asr
python scripts/runtime_setup.py plan qwen_asr_model
python scripts/runtime_setup.py plan qwen_aligner_model
```

FFmpeg 计划给出当前探测状态和操作系统包管理器提示。VideOCR 默认选择当前平台 CPU 资产；
Agent 只有在当前驱动和任务实际需要时才改选 CUDA 变体。ASR 计划列出固定 Python、torch、
qwen-asr 与 transformers 组合；模型计划列出固定仓库与 revision。

除 FFmpeg 外，`install` 都必须显式携带 `--confirm-large-download`。确认前向用户报告选择、
目标位置、已知字节数或模型成本、revision 与 lock 哈希；确认后由 Agent 执行下载/环境创建。
VideOCR 下载完成先校验字节数和 SHA-256，再解压并持久化 CLI 路径。模型安装生成文件哈希
回执；迁移或怀疑损坏时用完整 `verify`，仅做快速启动检查时才用 `--quick`。最后必须重跑
setup 与 doctor，不能把“文件存在”当成能力 ready。

ASR 环境与模型目录开始安装时会写入 `.video-subtitle-installing.json`。下载或安装中断后，
用完全相同的 profile/revision 和目标目录再次执行 `install`，工具会复用可恢复的半成品；
不同计划不会混用该目录。验证成功后 marker 自动删除。不要为了绕过冲突手工改 marker；应先
核对锁和目标，确需更换计划时改用新的空目录。ASR 新环境还必须由锁中声明的 Python 3.12
创建，现有环境的 Python、torch、qwen-asr 与 transformers 会一起校验。

## 能力矩阵

| 能力 | 用途 | 关键依赖 |
| --- | --- | --- |
| `watch_later_monitor` | 读取 Bilibili 稍后再看并发现新增任务 | Python、Node、OpenCLI、仓库 Watch Later 插件、Browser Bridge |
| `platform_subtitle` | Bilibili 元数据和平台字幕 | Python、Node、OpenCLI、Browser Bridge |
| `video_download` | 获取一次认证视频 | 平台能力、yt-dlp、FFmpeg |
| `hard_ocr_local` | 对本地视频做硬字幕 OCR | Python、VideOCR |
| `hard_ocr_url` | 下载后做硬字幕 OCR | 下载能力、VideOCR |
| `audio_asr_local` | 对本地视频做 Qwen3-ASR | FFmpeg、ASR 环境、两个模型、CUDA |
| `audio_asr_url` | 下载后做 Qwen3-ASR | 下载能力、ASR 环境、两个模型、CUDA |

### `watch_later_monitor` 安装顺序

稍后再看监控不是 OpenCLI 内置命令，而是仓库分发的只读插件能力。setup 必须先返回并执行
Agent 可完成的安装动作：固定版本 OpenCLI、`opencli-plugin` 本地插件、命令验证；只有这些
依赖就绪后，Browser Bridge 登录才成为 human action。不要因为检测到浏览器未登录，就跳过
插件安装并提前向用户索要登录处理。

验证命令：

```powershell
opencli video-subtitle-watch-later --help
opencli validate video-subtitle-watch-later/list
video-subtitle doctor --capability watch_later_monitor
```

该 capability 只证明当前机器能够读取稍后再看列表。自动化 profile、草稿授权、一次扫描、
任务状态机和周期调度见 [`watch-later-automation.md`](watch-later-automation.md)。仓库本身不
注册 daemon 或真实定时任务；调用 Agent 负责每次 one-shot 唤醒。

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

当同一轮同时存在 Agent 与 human 动作时，顶层状态保持
`agent_action_required`：`human_actions` 可以作为后续计划被观察，但必须先执行
Agent 动作并重跑 setup。CUDA 只有在 FFmpeg、独立 ASR Python、ASR 模型与 Aligner
都就绪并完成运行时探测后，才可能成为 `human_action_required`；在此之前它只会标为
`blocked`，不会把软件未安装误报成用户缺少硬件。

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
- `opencli_browser_timeout`
- `download_retries`
- `download_retry_backoff`
- `download_cache`
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

## 下载可靠性与缓存

下载策略属于可持久化执行配置，不是新的 capability。默认值为：

- OpenCLI 浏览器命令超时：180 秒；
- 瞬时下载失败重试：2 次；
- 线性退避基数：2 秒；
- 后台 job 缓存：`<VIDEO_SUBTITLE_HOME>/cache/media`。

可通过 CLI、环境变量或配置文件覆盖：

| 配置字段 | 环境变量 | 作用 |
| --- | --- | --- |
| `opencli_browser_timeout` | `VIDEO_SUBTITLE_OPENCLI_BROWSER_TIMEOUT` | 单次 OpenCLI 浏览器命令超时秒数 |
| `download_retries` | `VIDEO_SUBTITLE_DOWNLOAD_RETRIES` | 瞬时或结果不确定错误后的额外尝试次数 |
| `download_retry_backoff` | `VIDEO_SUBTITLE_DOWNLOAD_RETRY_BACKOFF` | 第 N 次重试前等待 `基数 × N` 秒 |
| `download_cache` | `VIDEO_SUBTITLE_DOWNLOAD_CACHE` | 同步任务和跨任务共享的媒体缓存根目录 |

后台 job 在未显式指定缓存时自动使用 home 下的缓存；同步 `extract` 不擅自选择跨目录缓存，
必须通过 `--download-cache` 或持久配置启用。缓存键包含平台、BVID、分 P 和清晰度，避免把
不同媒体误当成同一文件。缓存标记同时保存真实文件大小；文件缺失、为空或大小与标记不一致
时自动失效。缓存只保存媒体和非秘密元数据，不保存 Cookie、Token 或浏览器存储。

下载成功的 manifest attempt 记录缓存命中、重试次数、真实绝对路径和落盘字节数。诊断与
性能分析必须使用 `actual_bytes` / `actual_mib`，不能相信 OpenCLI 的展示型大小字段。

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
7. URL 媒体任务复用持久缓存；同步任务没有配置缓存时应显式决定是否需要跨任务复用。
8. 下载验收读取 manifest 的真实文件大小、缓存和重试字段，不读取展示型 `size` 作为事实。
9. 只有 requested capabilities 全部 ready 才进入提取。
10. 失败时保留 setup、doctor、manifest 和日志作为下一轮诊断证据。

## 扩展契约

新增外部依赖时：

1. 在 `requirements.json` 的 `dependencies` 中定义唯一 ID、类型、描述和动作；
2. 只把它加入真正需要的 capability；
3. 在诊断层返回 `ready`、`missing`、`blocked` 或
   `human_action_required`；
4. 若有配置字段，同时加入 config 映射和配置 schema；
5. 为 Agent/human 分流、配置优先级和缺失上游项添加测试；
6. 更新 Skill，而不是把不可判断的语义决策写进安装脚本。

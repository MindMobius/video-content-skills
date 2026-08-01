# Video Subtitle Skill 工具架构

## 目标

输入受支持的平台链接或本地视频后，为调用方提供可独立读取、按需补充、可追溯
的字幕证据。系统不把一种识别结果包装成真相，也不预先规定调用方必须怎样校对。
当前版本只实现 Bilibili 平台适配器。

## 职责边界

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| 工具 | 登录态、下载、OCR、ASR、时间轴、缓存、文件与格式校验 | 跨语言语义判断、翻译取舍、决定下一步 |
| Agent | 选择来源与时间范围、比较语义、发现疑点、决定是否补证 | 手工解析 SRT、猜测工具状态、直接改写原始证据 |
| Skill | 能力地图、证据边界、工具使用建议 | 固定步骤、强制全片 ASR、强制遍历审阅窗口 |

原始平台字幕、OCR 和 ASR 始终是独立证据。修订结果只能作为新的派生产物保存。

## 可组合执行循环

Agent 根据当前任务反复执行最小循环：

```text
观察状态或证据目录
→ 提出一个具体疑问
→ 调用最窄的工具和时间范围
→ 比较证据并作出判断
→ 信息足够则停止，否则继续补证
```

典型例子：

- 只需要快速总结：先取平台字幕；不存在时再运行硬字幕 OCR。
- 需要核对 06:04 的漏句：只读取该时间段 OCR/ASR，必要时只重跑这一段。
- 专业术语密集：收集多来源，但 Agent 只审阅影响结论的冲突。
- 需要交付完整精校 SRT：可以使用可选的固定窗口助手持久化全片决策。

## 证据获取

`start_subtitle_extraction` 仍是便捷的采集入口，但其产物只是证据，不是强制
工作流：

1. 平台适配器解析链接、分集、时长和平台字幕；当前 Bilibili 适配器使用
   OpenCLI 与 Browser Bridge 登录态。
2. Agent 按需启用 VideOCR 和 Qwen3-ASR。
3. 视频只下载一次，或复用调用方提供的本地文件。
4. 每一路结果分别写入 SRT、JSON、Markdown 和 manifest。
5. 多来源完成后状态为 `independent_evidence`，不会自动生成审阅包。

默认主证据优先级仍为：

```text
platform_subtitle > hard_ocr > audio_asr
```

它只为快速消费提供默认值。Agent 可以通过 `list_subtitle_evidence` 看见全部
来源，再用 `read_subtitle_evidence` 选择任意来源和毫秒时间范围。

## 平台适配边界

采集核心只依赖 `platforms/base.py` 中的最小接口：

- `video`：读取统一元数据；
- `subtitles`：读取平台可用的字幕 cue；
- `download`：在 OCR 或 ASR 确实需要时取得视频文件。

Bilibili 的 OpenCLI、Browser Bridge、短链接和分 P 逻辑都留在
`platforms/bilibili.py`。后续 YouTube、抖音适配器不能把登录态或平台专用字段
反向塞进 `core/`、`backends/`。

## 原子证据工具

### `list_subtitle_evidence`

返回每份可按时间读取的字幕证据，包括：

- `evidence_id`；
- 来源和来源类型；
- 原始层或派生层；
- cue 数量；
- 是否为默认稿；
- 文件是否仍然可读。

### `read_subtitle_evidence`

输入 `evidence_id`、`start_ms`、`end_ms` 和 `max_cues`，返回与该范围重叠的
字幕。响应包含稳定 cue ID、绝对时间戳、分页状态和下一段起点。Agent 不必先
生成 30 秒窗口，也不必把全片字幕塞进上下文。

## OCR 与 ASR

VideOCR 支持字幕区域裁剪、全帧和双尺度 OCR。双尺度共识只是画面文字过滤
证据，不代表识别结果一定正确。

Qwen3-ASR 将音频转成 16 kHz 单声道并由 Forced Aligner 提供时间戳。全片 ASR
默认不注入上下文；术语上下文只用于已发现的短时间冲突。如果模型回显上下文，
worker 自动无上下文重跑并保留原始输出。

外语音频和中文字幕只能按时间与语义比较。ASR 可以证明某一段存在语音或 OCR
可能漏句，但不能独自证明同音人名、数字或专业术语的正确写法。

## 可选固定窗口助手

`prepare_subtitle_review`、`get_subtitle_review_window` 和
`submit_subtitle_review_window` 是兼容保留的批处理助手：

- 适合需要完整精校字幕的任务；
- 可以生成固定时间窗和启发式疑点；
- 可以持久化 `keep/replace/delete/insert` 与未决项；
- 不再由抽取流程自动执行；
- 高优先级和规则标记都只是建议，Agent 可以忽略并自行取证。

原始 OCR/ASR 不会被修改。只有调用该助手时才生成 `review.packet.*`、
`subtitle.reviewed.*` 和 `review.report.*`。

## 状态语义

- `queued/running`：采集还在执行。
- `needs_ocr`：没有可用字幕，且需要配置或启用 OCR；不是成功。
- `completed`：至少取得一路证据，不代表多来源已融合。
- `fusion_status=independent_evidence`：多路证据可供 Agent 选择，尚无语义结论。
- `review.status=ready_for_agent_review/in_progress`：可选批处理助手正在使用。
- `agent_review_complete`：仅表示固定窗口助手全部完成。

是否已经满足用户请求，由 Agent 根据任务风险和证据充分性判断，而不是由统一
流水线替它决定。

## 当前下一步

现有原子层已经支持证据目录和按时间读取。后续应继续增加按范围抽帧、局部 OCR、
局部 ASR、通用派生修订，以及 YouTube、抖音平台适配器，而不是继续扩大启发式
审阅规则。

# 技术选型与复用边界

这不是“市场上没有工具，所以从零写 OCR”。现有项目各自覆盖了一段，但没有一个现成项目同时满足 B 站登录态、完整硬字幕时间轴、后台任务、MCP、Skill 和稳定 JSON 产物。

| 项目 | 能直接复用的部分 | 不足以单独解决的问题 | 本项目中的位置 |
|---|---|---|---|
| [OpenCLI](https://github.com/jackwener/OpenCLI) | Browser Bridge 登录态、B 站元数据、平台字幕、带 cookie 下载 | 不是 MCP Server；平台字幕结果不暴露最终轨道类型；下载结果不返回绝对文件路径 | B 站 transport/auth adapter |
| [mcp-video-analyzer](https://github.com/guimatheus92/mcp-video-analyzer) | 成熟的 MCP + Skill + CLI 形态；原生字幕优先、Whisper 兜底；关键帧 Tesseract OCR | OCR 面向最多约 60 张关键帧的画面文字，不是逐字幕变化构造完整 SRT；当前支持列表未把 B 站当作一等平台 | 后续 ASR、关键帧和多源佐证的参考实现 |
| [video-subtitle-extractor (VSE)](https://github.com/YaoFANGUK/video-subtitle-extractor) | 字幕区域检测、抽帧、PaddleOCR、相似文本去重、时间轴/SRT 后处理 | README 中的 CLI 实际仍用 `input()` 询问视频和区域；配置与输出路径依赖内部状态，不适合无交互 agent | OCR 算法和后处理参考 |
| [VideOCR](https://github.com/timminator/VideOCR) | 完整非交互 CLI；底部区域默认值；PaddleOCR；GPU；裁剪、跳帧、置信度与时间范围 | 本身不负责 B 站登录/下载，也没有 MCP/任务状态 | 第一个硬字幕 OCR 后端 |
| [RapidVideOCR](https://github.com/SWHL/RapidVideOCR) | 可 pip 安装、将 VideoSubFinder 的关键字幕帧转成 SRT/ASS/TXT | 主要输入是 VideoSubFinder 产生的 `RGBImages`/`TXTImages`，不是直接视频 | 未来可选的两阶段后端 |

## 核心判断

`mcp-video-analyzer` 的 OCR 并非无效。它很适合识别演示画面中的按钮、代码、报错和少量覆盖文字，也适合给音频转写提供视觉佐证。但对“8 分钟口播视频中每次变化的硬字幕都必须进入 SRT”这个目标，几十张关键帧在采样定义上就不可能保证完整覆盖。

因此这里没有复制 OCR 算法，而是用 Skill、MCP 和 CLI 组合现有能力：

1. 用 OpenCLI 复用真实浏览器登录态和 B 站接口；
2. 优先获取平台已存在的字幕；
3. 只有缺平台字幕且 OCR 后端可用时才下载视频；
4. 把 VideOCR 作为可替换进程调用；
5. 可选运行高、低分辨率两次 OCR，用低分辨率时间轴过滤只在高清稿出现的小号场景文字；
6. 将终态、逐步尝试、日志和产物统一到 `manifest.json`；
7. 用 MCP 后台任务避免长时间下载/OCR 阻塞一次工具调用；
8. 用 Skill 约束 agent 不把 `EMPTY_RESULT` 或 `needs_ocr` 误当成功。

## VideOCR v1.5.1 源码结论

对 VideOCR CLI 源码逐段核对后，可以确定：

- `brightness_threshold` 只是将低于阈值的像素置黑，不会按文字框类型过滤；
- `subtitle_position=center` 只取裁剪画面中央 30% 做初始 SSIM 帧变化比较，不会删除偏离中心的 OCR 框；
- PaddleOCR 的检测框用于相邻帧去重，但最终识别仍覆盖整个裁剪区域；
- 因此，当网页、商店或 Codex 窗口的小字刚好进入字幕带时，单次高分辨率 OCR 会把它与硬字幕一起写进 SRT。

本项目的双尺度模式不是简单“取较低清晰度的结果”。低分辨率稿提供时间轴与大字幕存在性，高分辨率稿的完整文本或连续行窗口只有在同一时间段与低分辨率文字相似时才进入最终稿。验证覆盖不足则回退主稿，两份原始 SRT 始终保留。

## 已实现边界

当前已经具备 Qwen3-ASR、Forced Aligner、双尺度 OCR、独立证据目录、按时间范围
读取，以及可选的 OCR/ASR 固定窗口审阅。启发式规则只负责提出候选，不会自动
裁决跨语言语义或反向改写原始字幕。

## 下一阶段

- 按时间范围抽取视频帧，让调用方直接核对疑难 OCR；
- 局部重跑 OCR/ASR，而不是为一个疑点重复整条视频；
- 通用派生字幕修订工具，脱离固定窗口助手也能保存可审计修改；
- YouTube 与抖音平台适配器；
- `visual_keyframe_ocr` 证据，用于保存非字幕画面文字。

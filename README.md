# Video Subtitle Skill

一套让 Agent 按需获取、读取和核验视频字幕证据，并把已核验内容转换为合适媒介的
Skill、MCP Server 与 JSON CLI。

它不会把平台字幕、硬字幕 OCR 或音频 ASR 自动拼成“唯一正确稿”。工具负责依赖
检查、登录态、下载、识别、时间轴和产物；Agent 负责选择证据、理解语义、判断冲突
并决定是否继续取证。

仓库包含四个可发现 Skill：`video-subtitle` 负责建立证据，`video-to-content`
负责把证据重建为可追溯的内容模型并生成审计成品；`wechat-draft-handoff` 只在明确授权下
把已审计公众号文章放入已登录编辑器并保存草稿；`video-watch-later-automation` 负责把已经
选定的“Bilibili 稍后再看 -> 微信公众号草稿”长期工作流编排起来。普通单视频任务没有指定
载体时，Agent 仍必须等待用户选择或明确委托；只有 standing profile 已经固定微信公众号文章
时，自动化周期才不再逐条询问。语义判断始终由 Agent 完成，工具只做依赖、持久化、版本和
确定性校验。

Python/MCP 内容项目的终点仍是忠实、得体、恰当、优雅且通过审计的可交付成品。可选草稿
交接不属于默认链路，不读取登录秘密，也不反向修改审计产物。定时发布、正式发布、群发、
原创声明、变现和账号管理均不属于本项目职责。

## Agent 快速入口

仓库内的四个 Skill 位于标准项目目录 [`.agents/skills`](.agents/skills)，支持该约定的
Agent 在进入仓库后可以直接发现。其他项目或个人环境可先检查再安装：

```powershell
npx skills add MindMobius/video-subtitle-skill --list
npx skills add MindMobius/video-subtitle-skill `
  --skill video-subtitle `
  --skill video-to-content `
  --skill wechat-draft-handoff `
  --skill video-watch-later-automation
```

不支持 Agent Skills 自动发现的 Coding Agent 应从 [`AGENTS.md`](AGENTS.md) 开始；它会
把任务路由到对应 Skill，并给出全新机器的 bootstrap、依赖检查、人机边界和验证规则。
Skill 负责告诉 Agent 如何判断和使用工具，不会假设 MCP 已经注册；MCP 不可用时使用同契约
的 JSON CLI。可验证范围、干净 clone 验收和非确定性边界见
[`docs/reproducibility.md`](docs/reproducibility.md)。

## DSH 插件试玩

仓库同时提供一个最小的 DeepSeek Harness Bundle。它不重写 Python 核心：Bundle 将上述四套
Skill 注册到 DSH，并用 DSH 官方 MCP Client 连接现有 stdio MCP Server。当前原型没有专用
UI，先验证自然语言入口、Skill 路由和 35 个工具能否作为一个完整垂直能力共同工作。

在本地 clone 中完成一次 Python bootstrap，再把当前目录安装到 DSH 的 `web` profile：

```powershell
python scripts\bootstrap.py --apply
dsh plugin --profile web add .
dsh --profile web --dump-config
dsh web
```

安装后可以直接说：

```text
把这个 B 站视频整理成一篇可追溯的公众号文章，先不要保存到公众号。

运行我已经授权的稍后再看到公众号草稿自动化周期。
```

Bundle 默认使用仓库 `.venv` 中的 Python；可用 `VIDEO_SUBTITLE_DSH_PYTHON` 指向另一个已安装
本项目及 MCP 依赖的 Python。公众号草稿交接仍需用户明确授权和可控制的已登录浏览器；安装
此 Bundle 不代表获得发布、群发或账号管理权限。

## 当前能力

- Bilibili 普通链接、短链接和分 P；
- OpenCLI Browser Bridge 登录态与平台字幕；
- URL 媒体下载的 180 秒默认超时、有限重试、持久缓存和真实落盘大小统计；
- 本地视频或下载视频的 VideOCR 硬字幕时间轴；
- 连续硬字幕不确定时的稀疏 OCR 侦察窗口计划；
- Qwen3-ASR 与 Forced Aligner 音频时间轴；
- OCR 与 ASR 独立执行、按机器资源安全调度；
- 按来源、按任意时间范围读取字幕证据；
- 可选的固定窗口精校与不可变原始产物；
- 面向 Agent 的依赖检查、配置持久化和修复动作；
- 固定字幕 manifest 与各路证据哈希的内容工程项目；
- 与媒介无关的 content map，以及 claim—evidence—timestamp 引用；
- 用户授权的载体决策，以及由 Agent 完成的重构策略、叙述口吻、版本化成品和逐项忠实度审计；
- Agent 显式命名的内容阶段计时，以及按阶段名称、类别汇总的真实耗时；
- 公众号文章配图默认使用原视频封面和带时间点的可追溯截帧；自制结构图、AI 配图、图库图和
  其他合成视觉只有在用户明确要求或单独批准后才可使用；
- 首方 `restrained-editorial` 公众号渲染器：从结构化语义稿生成克制排版、干净 HTML、原视频
  视觉素材、单行相对图片路径、预览与导入清单，并拒绝非视频来源配图；
- 用户显式授权后的可选公众号草稿交接：剪贴板内临时装配本地图片、验证微信 CDN 接管、
  填写标题/摘要/封面、只保存草稿并生成与当前审计绑定的可校验回执；
- Bilibili 稍后再看自动化：新增发现、BVID + 分 P + profile 版本幂等入队、组合式证据/规范字幕
  状态操作、最佳字幕、文章审计、有界重试、`unprocessable` 失败关闭、`paused_auth` 登录暂停、
  单草稿 binding，以及可安全修复旧路径元数据的整库完整性审计；
- 多视频任务的逐条批次台账、阶段前置条件、失败重试和恢复点，不合并每条视频的独立产物；
- 项目 ZIP 导出、SHA-256 校验、秘密扫描、路径穿越防护和跨机器导入，默认排除原视频；
- `core`、`agent`、`media`、`live` 四层复现验收，其中 live 服务永远保持显式人工验证；
- 检测证据变化、过期媒介计划、未审计成品和缺失核心限定条件。

YouTube 与抖音平台适配器尚未实现。OCR、ASR、证据和审阅核心不依赖平台，新增
平台只需实现 [`platforms/base.py`](src/video_subtitle/platforms/base.py) 的最小接口。

## 稍后再看到公众号草稿自动化

当用户已经明确选择长期工作流并授予仅限 `save_wechat_draft` 的可撤销授权后，可以把
Bilibili“稍后再看”作为任务入口。仓库每次只执行一次扫描和一次队列推进；周期由调用方的
Codex automation 或其他调度器负责，不创建隐藏 daemon。证据不足会记录为
`unprocessable`，登录失效会记录为 `paused_auth`，任何路径都不会发布。Agent 优先使用
组合式 evidence/canonical 动作，并在每轮结束运行 `automation-audit`，用户只看最终摘要。

完整的 profile、授权、CLI/MCP、状态机、幂等规则和 live acceptance 说明见
[`docs/watch-later-automation.md`](docs/watch-later-automation.md)。

## Agent 可迁移环境

Python 包依赖写在 `pyproject.toml`；外部程序、模型、浏览器登录态和硬件依赖写在
机器可读的 [`requirements.json`](src/video_subtitle/requirements.json)。后者按能力
声明依赖，并把修复动作严格分为：

- `agent_actions`：Agent 应自行定位、安装或配置；
- `human_actions`：浏览器登录、硬件缺失等必须由人处理的边界；
- `confirmation_required`：模型等大体积下载，Agent 执行前需要确认成本。

Python 解析锁为 `uv.lock` 与 `requirements/mcp-constraints.txt`，Node 分发锁为会随 npm
包发布的 `npm-shrinkwrap.json`；VideOCR 资产、ASR 包组合、模型 revision 和哈希基线位于
[`runtime-lock.json`](requirements/runtime-lock.json)。`requirements.json` 负责说明“某项能力
需要什么”，runtime lock 负责说明“本版本验证了哪一个具体运行时”。升级必须同步更新锁、
schema、测试和 `verified_at`，不能在同一次任务中静默漂移到 `latest`。

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

# 对 setup 返回的重依赖先读取计划；大下载必须经用户确认后才 install
python scripts\runtime_setup.py plan videocr
python scripts\runtime_setup.py plan asr
python scripts\runtime_setup.py plan qwen_asr_model
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
  --videocr C:\path\to\videocr-cli.exe `
  --home C:\path\to\video-subtitle-home `
  --download-cache C:\path\to\shared-media-cache `
  --opencli-browser-timeout 180 `
  --download-retries 2 `
  --download-retry-backoff 2

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
硬字幕抽样计划由
[`ocr-scout-plan.schema.json`](schemas/ocr-scout-plan.schema.json) 定义。内容工程的项目、
内容地图、媒介计划和忠实度审计分别由
[`content-project.schema.json`](schemas/content-project.schema.json)、
[`content-map.schema.json`](schemas/content-map.schema.json)、
[`media-plan.schema.json`](schemas/media-plan.schema.json) 和
[`fidelity-audit.schema.json`](schemas/fidelity-audit.schema.json) 定义；已保存的公众号草稿回执由
[`wechat-draft-receipt.schema.json`](schemas/wechat-draft-receipt.schema.json) 定义。批次、迁移包、
公众号语义稿和浏览器无秘密观察分别由 `batch-manifest.schema.json`、
`portable-bundle.schema.json`、`wechat-manuscript.schema.json`、
`wechat-browser-snapshot.schema.json` 与 `wechat-editor-observation.schema.json` 定义。

## 使用流程

默认取证原则为：

平台字幕和硬字幕不是前后互斥的降级链，而是两条独立证据链：

1. 始终先查询便宜的平台字幕，但在平台没有明确证明时，不假定它是人工精校稿；
2. 无论平台字幕是否存在，都独立判断画面里是否有连续硬字幕；
3. 存在连续硬字幕时必须跑全片 OCR。对科普、访谈、翻译和术语密集视频，OCR 通常是发布者
   实际展示文字的主要证据，平台字幕和 ASR 用于校对；
4. 只有视觉侦察确认没有连续硬字幕，才跳过全片 OCR；
5. 无可用文字轨时以 ASR 兜底，高价值、外语或术语密集内容也可用 ASR 做独立语义校验；
6. 已知冲突优先局部重跑，不因一个词重新处理全片。

不能确认全片是否存在连续硬字幕时，不论平台字幕是否可用，都先用
`plan_hard_subtitle_scout` / `ocr-scout-plan` 计算开头、四分之一、中点、四分之三和结尾的
稀疏窗口，再让 Agent 根据画面、文字角色、cue 密度和连续性决定是否运行全片 OCR。少量 cue
不能证明没有硬字幕；已知连续硬字幕时直接进入全片 OCR，已知没有时才跳过。

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

## 多视频任务编排与耗时优化

多视频任务由 Agent 编排多个独立的单视频任务，并用 `video-content/batch-v1` 台账保存阶段状态
和恢复点；它不是“大批次合并稿”。每个输入仍保留自己的 `manifest.json`、content project、
deliverable、fidelity audit，以及用户明确要求保存草稿时才产生的 WeChat receipt。建议按用户
给定顺序推进：

1. 先为每个链接解析元数据和平台字幕，尽早暴露失效链接、分 P 与登录问题；
2. 独立侦察每条视频是否有连续硬字幕；这个判断不受平台字幕是否存在影响；
3. 侦察确认有连续硬字幕就跑全片 OCR，确认没有才跳过，并让后续 OCR/ASR 复用同一媒体缓存；
4. GPU OCR 与 GPU ASR 默认保持 `auto` 或 `serial`，不能因为任务多就盲目并行；
5. 内容项目用 `content_map`、`medium_decision`、`article_draft`、`visual_render`、
   `fidelity_audit` 和 `wechat_handoff` 等显式阶段记录真实墙钟时间；
6. 用 `get_video_content_project` / `content-status` 的按名称和类别汇总寻找瓶颈，不能用聊天
   时间戳或主观体感代替计时。

```powershell
video-subtitle batch-init --manifest .\batch\batch.json `
  --input $url1 --input $url2 --medium article --draft
video-subtitle batch-status --manifest .\batch\batch.json
video-subtitle batch-update --manifest .\batch\batch.json `
  --item-id item-001 --stage subtitle --status running
video-subtitle batch-update --manifest .\batch\batch.json `
  --item-id item-001 --stage subtitle --status completed `
  --artifact .\batch\item-001\manifest.json
```

台账要求 subtitle -> content -> handoff 的前置条件，完成态必须指向批次目录内真实文件；单条失败
不会抹掉其他条目的成功状态。只有用户明确要求草稿时才创建 handoff 阶段。

后台 job 默认复用 `<VIDEO_SUBTITLE_HOME>/cache/media`；同步任务应持久化 `download_cache`
或显式传入 `--download-cache`。下载 attempt 中的 `actual_bytes`、`actual_mib`、`cache_hit`、
`cache_state`、`retry_index` 和 `attempt_count` 是运行回执。OpenCLI 自己展示的文件大小不是
验收依据。重跑同一平台、BVID、分 P 和清晰度时应命中缓存；改变这些身份字段会得到独立缓存键。

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

# 全片硬字幕是否连续还不确定时，先计算稀疏 OCR 窗口
video-subtitle ocr-scout-plan --duration-seconds 3600 --window-seconds 20
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
$init = video-subtitle content-init --manifest .\result\manifest.json | ConvertFrom-Json
$project = $init.project_path

video-subtitle content-save --project $project `
  --kind content_map --document .\content-map.json
video-subtitle content-save --project $project `
  --kind media_plan --document .\media-plan.json

$draftPhase = video-subtitle content-phase-start `
  --project $project --name article_draft --category agent | ConvertFrom-Json
video-subtitle content-deliverable `
  --project $project `
  --medium article --format markdown --content-file .\article.md `
  --title "文章标题" --used-claim-id claim-0001
video-subtitle content-phase-finish `
  --project $project --phase-id $draftPhase.phase.phase_id --status completed

video-subtitle content-save --project $project `
  --kind fidelity_audit --document .\fidelity-audit.json
video-subtitle content-validate --project $project
video-subtitle content-status --project $project

# 将通过审计的项目安全交给另一台机器或 Agent
python scripts\project_bundle.py export --project $project --output .\project.zip
python scripts\project_bundle.py verify .\project.zip
python scripts\project_bundle.py import .\project.zip --destination .\restored
```

完整工作流、状态失效规则和 dbskill 复用边界见
[`docs/content-workflow.md`](docs/content-workflow.md)。
真实的 16 分钟视频全链路结果见
[`BV1KHNC61ExM 内容转换实测`](docs/cases/BV1KHNC61ExM-content.md)。
按载体重构、使用联合作者口吻并输出 SVG/PNG 一图流的结果见
[`BV1v6Kf6rEYh 一图流实测`](docs/cases/BV1v6Kf6rEYh-one-page.md)。
公众号文章的完整协议见
[`公众号文章交付参考`](.agents/skills/video-to-content/references/wechat-article.md)；平台字幕与
硬字幕互证、作者口吻重构、可选 `gzh-design-skill` 排版、本地封面交接和双重验证的真实
运行见 [`BV1W8GP6nECY 公众号文章实测`](docs/cases/BV1W8GP6nECY-wechat-article.md)。复杂图片
占位组件如何在真实编辑反馈后收敛为“单行相对路径＋机器属性”，见
[`BV1xK3h6fE7a 最小图片交接实测`](docs/cases/BV1xK3h6fE7a-wechat-minimal-image-handoff.md)。
后续视频改编文章必须优先从原视频选择与正文语义对应的截帧，并记录时间点；文章请求不等于
授权生成结构图或 AI 配图，原视频没有合适画面时宁可减少配图。
已审计文章如何在不污染正式 HTML 的前提下，通过一次性富文本剪贴板把 7 张本地图片交给
微信、验证 CDN 接管并只保存草稿，见
[`BV1hK3v6LELB 公众号草稿交接实测`](docs/cases/BV1hK3v6LELB-wechat-draft-handoff.md)。
正文 DOM 含辅助图片节点时如何只统计可见、已加载的微信图片，作者口吻如何避免扩大事实授权，
以及封面和草稿保存怎样形成可靠收据，见
[`BV1jxREBSEUv 公众号草稿交接实测`](docs/cases/BV1jxREBSEUv-wechat-draft-handoff.md)。
生成公众号文章时，先建立 `video-content/wechat-manuscript-v1`，再运行
`python scripts/render_wechat_article.py <manuscript.json> <wechat-article-directory>`。首方渲染器会
生成并立即校验图片标记、文件、清单、正式 HTML 和预览文案；它只接受原视频封面和带时间点
截帧，语义内容与忠实度审计仍由 Agent 负责。已有包或第三方渲染结果仍可独立运行
`python scripts/validate_wechat_package.py <wechat-article-directory>`，不能因为未经过首方渲染就
跳过确定性包校验。
如果用户还明确要求保存公众号草稿，保存并回读页面后必须在文章包旁生成
`wechat-editor-observation.json`，再运行：

```powershell
python scripts/build_wechat_draft_receipt.py `
  <wechat-article-directory>\wechat-editor-observation.json `
  --project <content-project>\project.json `
  --output <wechat-article-directory>\wechat-draft-receipt.json
```

只有返回 `ok=true` 且 `validation.valid=true`，才能宣布草稿保存完成；回执必须绑定当前 deliverable 与 fidelity audit，
记录稳定 `appmsgid`、图片和元数据回读、持久化手动保存记录，并明确
`published=false`、`publish_actions_performed=[]`。

## MCP

MCP Server 使用 stdio，共暴露 24 个工具：

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

硬字幕侦察：

- `plan_hard_subtitle_scout`

可选精校：

- `prepare_subtitle_review`
- `get_subtitle_review_window`
- `submit_subtitle_review_window`

内容工程：

- `initialize_video_content`
- `get_video_content_project`
- `start_video_content_phase`
- `finish_video_content_phase`
- `save_video_content_document`
- `save_video_content_deliverable`
- `read_video_content_artifact`
- `validate_video_content_project`

批次台账：

- `initialize_video_batch`
- `get_video_batch`
- `update_video_batch_item`

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
├─ .agents/skills/video-subtitle/       字幕证据决策与安全边界
├─ .agents/skills/video-to-content/     内容重建、载体决策门、生成与审计 Prompt
├─ .agents/skills/wechat-draft-handoff/ 已审计公众号文章的可选草稿交接
├─ .agents/skills/video-watch-later-automation/ 稍后再看到单份微信草稿的自动化编排
├─ src/video_subtitle/
│  ├─ requirements.json               外部能力依赖契约
│  ├─ config.py                       持久配置与优先级
│  ├─ environment.py                  setup 动作规划
│  ├─ diagnostics.py                  quick/deep doctor
│  ├─ platforms/                      平台适配器
│  ├─ backends/                       OCR、ASR、Forced Aligner
│  ├─ core/                           SRT、证据、派生审阅、内容、批次与迁移包
│  ├─ wechat_renderer.py              首方克制排版公众号渲染器
│  ├─ wechat_adapter.py               剪贴板运输与无秘密草稿回执适配器
│  ├─ pipeline.py                     采集和资源调度
│  ├─ jobs.py                         持久后台任务
│  ├─ cli.py
│  └─ mcp_server.py
├─ requirements/                       Python 约束与重运行时锁
├─ scripts/bootstrap.py                无依赖安装入口与 Agent 运行契约
├─ scripts/runtime_setup.py            重依赖计划、确认安装和校验
├─ scripts/repro_check.py              四层可复现验收
├─ scripts/render_wechat_article.py    首方公众号文章包渲染与校验
├─ scripts/project_bundle.py            项目导出、验证和导入
├─ schemas/                            Bootstrap、环境、证据与内容契约
├─ tests/
├─ docs/reproducibility.md             干净 clone、CI 与真实媒体验收边界
└─ docs/watch-later-automation.md       稍后再看自动化的配置、调度与失败语义
```

## 开发验证

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts\mcp_smoke.py
npm test
npm run pack:check
python scripts\repro_check.py --require-tier core --require-tier agent
```

当前优先级是用更多授权真实长视频验证跨机器迁移、批次恢复和首方排版契约，增加按范围抽帧，
以及局部 OCR/ASR、通用派生修订、YouTube 和抖音平台适配器，而不是继续扩大固定启发式审阅
或摘要规则。

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
2. `.agents/skills/*/SKILL.md`：字幕取证与内容转换决策；
3. `src/video_subtitle/requirements.json`：能力依赖、已验证版本与模型 revision；
4. `schemas/`：Bootstrap、setup、证据与内容产物的机器契约；
5. `tests/`：确定性行为；
6. `docs/cases/`：观察性真实运行记录，不是可离线重放的测试 fixture。

## 干净 clone 验收

基础要求是 Python 3.10 或更高版本。Skill 安装器验收还需要 Node.js 20 或更高版本。
在仓库根目录执行：

```text
npx -y skills@1.5.22 add . --list
python scripts/bootstrap.py --apply --config .video-subtitle-local/config.json --capability hard_ocr_local
```

验收 Bootstrap 返回的单份 JSON：

- `schema_version` 为 `video-subtitle/bootstrap-v2`；
- `installation.ready=true`；
- `skills.available` 恰好包含 `video-subtitle` 与 `video-to-content`；
- `cli.command` 携带同一绝对配置路径；
- `mcp.transport=stdio`，且 `mcp.env.VIDEO_SUBTITLE_CONFIG` 指向同一配置；
- 缺少 VideOCR 时返回 Agent 动作，而不是虚假的 ready 或无关的人类动作。

随后由 Agent 处理当前任务所需的最小能力：

```text
<bootstrap 返回的 cli.command> setup --capability <capability>
<bootstrap 返回的 cli.command> doctor --capability <capability> --deep
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
```

CI 在 Windows 与 Ubuntu、Python 3.10 与 3.12 上运行完整测试；另有一个干净 Ubuntu
任务实际执行固定版本 Skill discovery 和 Bootstrap apply。macOS 尚未进入自动验收矩阵，
不能只凭代码看起来可移植就宣称已经验证。

## 真实媒体验收边界

登录 Bilibili、下载受版权约束的视频、运行 GPU OCR/ASR 和下载大模型不适合放进公共 CI：
它们需要用户会话、硬件、网络成本和内容授权。真实验收应选择用户有权处理的样本，完成：

1. setup/deep doctor；
2. 平台字幕、OCR、ASR 独立落盘；
3. manifest、attempt、日志与 SHA-256 保留；
4. 按时间范围读取并核对冲突；
5. 用户指定载体后再建立 content map、media plan、成品和 fidelity audit。

`docs/cases/` 只证明某个日期、某台机器和某组上游输入曾真实跑通。远端视频可能删除或
改版，仓库也不分发原视频、模型或登录凭证，因此这些文档不能冒充一键 replay fixture。

## 升级纪律

- 工具或模型升级必须更新 `requirements.json` 的 `verified_at` 与对应 version/revision；
- 不把“latest”静默混入声称可复现的任务；
- 模型目录必须对应记录的 revision，大下载仍需事前确认；
- 升级后先跑 schema、单元测试、MCP smoke 和干净 clone，再用代表性真实样本验证；
- 新机器或驱动变化后恢复 `media_execution=auto`，不得继承旧机器的并行结论。

## 当前明确限制

- 平台适配目前只有 Bilibili；YouTube 与抖音尚未实现；
- MCP 注册由调用 Agent 完成，仓库只提供可移植的 stdio 参数与 CLI fallback；
- 自动登录、发布公众号、写草稿箱和账号管理不属于项目职责；
- 没有外部真值集时不报告 OCR/ASR 的虚构准确率；
- 外部事实核验是独立工作，字幕多源一致不等于事实为真。

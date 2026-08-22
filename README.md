# Video Content Skills

面向 Agent 的视频证据与内容生产 Skill 集。

用户可以只给一个 Bilibili 视频链接，或把视频加入“稍后再看”。Agent 负责取得多来源字幕
证据、判断哪份更可靠、生成可追溯 Transcript，并把创作者原有的结构、专业程度和语气高保真
迁移到指定载体；在明确授权后可保存到微信公众号草稿箱。项目永不发布。

## 项目解决什么

- 获取 Bilibili 元数据、平台字幕和持久视频缓存；
- 用硬字幕侦察、VideOCR 和 ASR 补充或交叉校验证据；
- 保留原始证据，由 Agent 形成规范 Transcript；
- 把 Transcript 转成经过审计的来源忠实书面版或其他载体；
- 扫描 Bilibili 稍后再看，幂等创建和恢复任务；
- 复用可见的微信登录状态，保存且验证一份草稿收据。

工具只负责确定性采集、持久化、校验和平台边界；Agent 负责语义修复、视觉判断和必要的
口语转书面语，但默认不替创作者重新选题、增加观点或套用固定公众号文风。

## Agent 任务路由

先读 [`AGENTS.md`](AGENTS.md)，再只加载命中的 Skill：

| 需求 | Skill |
| --- | --- |
| 视频链接、本地媒体、字幕、OCR、ASR、证据校正 | [video-evidence](.agents/skills/video-evidence/SKILL.md) |
| 已有可信 Transcript，需要来源忠实的文章或其他载体 | [video-to-content](.agents/skills/video-to-content/SKILL.md) |
| 扫描、排空、重试或恢复稍后再看队列 | [watch-later-to-wechat](.agents/skills/watch-later-to-wechat/SKILL.md) |
| 把已审计文章保存到已登录微信编辑器 | [wechat-draft](.agents/skills/wechat-draft/SKILL.md) |

普通单视频任务未指定输出载体时，先完成证据与 Transcript；不要因为仓库支持微信就自动选择
公众号文章。已有 Watch Later Profile 时按 Profile 选择的载体执行。

## 六种核心产物

```text
Profile -> Job -> Evidence -> Transcript -> Content -> Draft Receipt
```

- **Profile**：授权来源、载体、扫描基线和非秘密运行偏好；
- **Job**：一个视频的状态、重试、恢复和幂等身份；
- **Evidence**：平台、OCR、ASR、封面、截帧等不可变观察；
- **Transcript**：Agent 基于 Evidence 形成的规范字幕；
- **Content**：将来源表达高保真迁移到指定载体并审计后的内容；
- **Draft Receipt**：微信草稿的可验证平台状态，固定 `published=false`。

多视频通过 `run_id` 查询 Job，不维护独立 batch/project/phase 协议。

## 渐进式读取

1. `README.md`：项目意义与 Skill 路由；
2. `AGENTS.md`：仓库级不变量；
3. 任务命中的 `SKILL.md`：主流程和边界；
4. Skill 的 `references/`：仅在当前分支需要时读取；
5. [`docs/architecture.md`](docs/architecture.md) 与
   [`docs/operations.md`](docs/operations.md)：维护或诊断时读取。

`.agents/skills/` 是唯一 canonical source。维护规则见
[`docs/skill-maintenance.md`](docs/skill-maintenance.md)。

## 新机器入口

```powershell
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --config <config-path> --capability <required-capability>
```

Bootstrap 返回一个 JSON 环境合同。Agent 先执行普通安装和路径发现，只把浏览器登录、硬件/权限
边界和确认的大下载交给用户。

运行入口：

```text
video-content ...
video-content-mcp
```

CLI 以 `system/source/evidence/job/content/watch-later/wechat` 分组；MCP 只暴露 16 个与这些
资源对应的动作。

## 不变量

- 当前 URL 平台只支持 Bilibili；
- 平台字幕存在，不代表画面没有连续硬字幕；
- 原始平台、OCR、ASR 和 Agent 校正证据分别保存，不互相覆盖；
- 公众号配图默认只用原视频封面和时间戳截帧；
- OCR/ASR 共用 GPU 时默认串行；
- 技术失败重试，物理证据不足标记 `unprocessable`，真实登录边界标记 `paused_auth`；
- 不请求或持久化 cookie、密码、token、浏览器存储或剪贴板正文；
- 不创建隐藏 daemon；
- 永不发布、群发、排期、声明原创、变现或管理账号。

## 验证

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts/mcp_smoke.py
npm test
npm run pack:check
python scripts/repro_check.py --require-tier core --require-tier agent
```

真实 Bilibili、OCR/ASR、Browser Bridge 和微信编辑器属于单独授权的 `live` 验收，不能从
离线测试推断成功。

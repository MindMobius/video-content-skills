# 架构

## 一句话

Video Content Skills 把视频处理拆成“确定性取证与持久化”以及“Agent 判断与转换”两层。
工具不替 Agent 决定哪份字幕正确；Agent 不绕过 Store、哈希、状态机和平台授权边界。

## 六种持久产物

### Profile

描述授权来源、载体、扫描基线和非秘密设置。Profile 不保存 cookie、token 或浏览器存储。

### Job

一个视频一个 Job。稳定 source identity 保证幂等；`run_id` 只用于查询同次扫描发现的多个
Job。阶段单向推进：

```text
queued -> inspecting -> evidence -> transcript -> content -> handoff -> completed
```

控制状态包括 `retryable`、`paused_auth`、`unprocessable` 和 `failed`。

### Evidence

保存平台字幕、OCR、ASR、下载清单、侦察结果、封面和时间戳帧等不可变观察。不同来源不能
原地互相覆盖。

### Transcript

Agent 对 Evidence 的规范化结果，包含证据选择、校正、未解决不确定性和质量结论。Content
只从 Transcript 取正文事实。

### Content

默认将 Transcript 的来源结构、人物关系、案例、限定、专业密度和语气高保真迁移到用户
指定载体，同时把逐条字幕恢复为可阅读的书面稿；机械拼接 cue、定长分段或少量正则补标点
仍然只是 Transcript 预处理，不是 Content。Content 同时保存媒体计划、渲染结果和来源忠实
审计。Watch Later Profile 的审计还要求
`material_sections.items` 的 cue-to-block 全量映射、显式 `omissions` 和带 `block_index` 的逐帧
`visual_plan`。Content media 必须与正文 image block 按顺序一致。最低截图数只是防止遗漏，Agent
仍按真实论述和视觉转场决定数量。完整成稿后，Agent 只对自己新增或载体适配的标题、转场、
总结和证据边界做来源感知表达审校，并把结果保存为 `expression_audit`；来源真实表达和专业
信息密度优先，不套固定公众号文风。只有用户明确要求时才进行摘要、受众改写、文风模仿或
重新组织论证。程序使用组合式高风险信号阻止明显的字幕直贴，并验证表达审校是否真实指向
最终文档，但不扫描所谓“AI 味”、不自动改写，也不计算文风分数。语义完整性和实际可读性仍由
Agent 对照来源判断。Content 不代表平台状态，也不授权保存。

### Draft Receipt

微信草稿的可验证状态：当前 Content 哈希、稳定 `appmsgid`、图片/封面/摘要、创作来源、
刷新回读和 `published=false`。一个 Job 同时最多一份当前有效收据；原位修订保留旧 Receipt，
新 Receipt 用 `supersedes_receipt_id` 接续，并强制保持同一 `appmsgid`。

## Store

活动状态只允许落在仓库根目录下被 Git 忽略的 `.video-content/`：

```text
.video-content/
  config.json
  profiles/<profile_id>.json
  jobs/<job_id>/job.json
  jobs/<job_id>/events.jsonl
  jobs/<job_id>/artifacts/<kind>/<artifact>
  cache/media/
  indexes/
  locks/
  meta/                       # 迁移、重定位和布局管理回执
    migration-receipt.json
    path-relocation.json
    state-layout.json         # 迁移时的布局快照
  runs/<run_id>/              # 当前运行的临时工作区
  archive/<date>-<reason>/    # 已保留但不再参与运行的历史材料
```

`config.json` 是唯一活动配置入口。CLI、MCP 和直接 API 会自动发现仓库本地配置；隔离测试必须同时显式传入独立 `--config` 和 `--home`，不能只创建一个临时 Store。迁移回执固定存放在 `meta/migration-receipt.json`；历史绝对路径由 `meta/path-relocation.json` 解释，不改写原始 Artifact。
完整规则见 [`docs/repository-layout.md`](repository-layout.md)。

写入使用同目录临时文件和原子替换。Artifact ID 同时绑定 kind 与内容哈希，允许相同字节以
不同语义角色存在，但不允许同一引用被不同字节覆盖。

## API 层

CLI 和 MCP 调用 `src/video_content/api.py` 的同一服务函数。CLI 按资源分组；MCP 固定 16 个
工具：系统 3、来源/证据 2、Job/Artifact 6、内容 3、稍后再看 1、微信 2。

## 数据流

```text
Bilibili/local media
  -> Evidence artifacts
  -> Agent Transcript
  -> source-faithful written edition
  -> section / visual / source-aware expression audit
  -> validated Content
  -> optional visible WeChat handoff
  -> validated Draft Receipt
```

定时触发不在仓库内。Codex automation 只重复调用一次扫描和 Job 操作。

## 完成证据分层

这条链路不是“有文件就算完成”。每个阶段只对自己的事实负责：

```text
Evidence -> Transcript -> Content -> Handoff -> Draft Receipt
   取到       可用         可读可追溯     已放入编辑器       刷新后仍存在
```

- Evidence 证明来源观察已经取得，不证明字幕选择或文章质量；
- Transcript 证明 Agent 已完成证据选择、校正和不确定性记录，不证明已经书面化；
- Content 证明正文保留实质章节、专业密度、观点归属和必要限定，并且章节与截图可追溯；
- Handoff 只代表一次可见平台交接，不代表保存成功；
- Draft Receipt 必须绑定当前 Content 哈希、稳定数字 `appmsgid`，并有刷新后的正文/图片/封面/摘要/创作来源回读。

因此，渲染结果、文章长度、媒体数量、保存 Toast、上传完成或 `appmsgid` 都不能越级充当完成证据。

## Agent 与程序边界

Agent 负责语义和视觉判断：实质章节、需要保留的细节、口语书面化、来源表达归属、最小表达修订、
画面转场和截图理由。程序负责可确定的高风险条件：哈希、路径、索引、媒体顺序、
`raw Transcript passthrough`、`expression_audit` 指向最终文本、授权、幂等、回读字段和
`published=false`。程序可以阻止明显假完成，但不把重合率或规则命中数当作文风评分器，也不替
Agent 发明一套固定公众号腔。

## 有副作用的重试

微信交接具有外部副作用，重试前必须先读取当前可见目标和已有 Receipt：

1. 读取同一页面或同一数字 `appmsgid`；
2. 刷新/重开并回读；
3. 只有确认没有当前有效 Receipt，才允许继续新建；
4. 修订只能复用原 `appmsgid`，以 `supersedes_receipt_id` 留存历史。

浏览器读取超时属于技术重试，真实登录页才是 `paused_auth`；不能因为一次超时就创建第二篇草稿。

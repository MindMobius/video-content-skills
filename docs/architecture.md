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

按用户指定载体重组的内容、媒体计划、渲染结果和审计。它不代表平台状态，也不授权保存。

### Draft Receipt

微信草稿的可验证状态：当前 Content 哈希、稳定 `appmsgid`、图片/封面/摘要、刷新回读和
`published=false`。一个 Job 最多一份有效收据。

## Store

默认目录：

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
```

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
  -> audited Content
  -> optional visible WeChat handoff
  -> validated Draft Receipt
```

定时触发不在仓库内。Codex automation 只重复调用一次扫描和 Job 操作。

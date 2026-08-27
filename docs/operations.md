# 运行与诊断

## 环境合同

首次运行或能力变化时：

```powershell
python scripts/bootstrap.py
python scripts/bootstrap.py --apply --config <config-path> --capability <capability>
```

只在 `setup.ready=true` 后启动对应能力。普通依赖安装和路径发现由 Agent 完成；浏览器登录、
硬件/系统权限和确认的大下载交给用户。

重依赖必须通过锁定计划：

```powershell
python scripts/runtime_setup.py plan <dependency>
python scripts/runtime_setup.py install <dependency> <reported-options>
python scripts/runtime_setup.py verify <dependency> <reported-options>
```

## 一次性状态迁移

从先前本机状态切换到 1.0 时，先 dry-run，再执行：

```powershell
python scripts/migrate_legacy_state.py --source <source> --archive <archive> --target <state> --expect-completed <count>
python scripts/migrate_legacy_state.py --source <source> --archive <archive> --target <state> --expect-completed <count> --apply
```

迁移要求三个绝对路径互不包含，源与归档位于同一卷，归档和新状态目标均不存在。执行时会为
全部源文件建立 SHA-256 清单、原子移动归档、复制并复核媒体缓存、建立 Profile 与已完成的
幂等 Job，最后把归档文件设为只读。历史引用漂移必须明确记录为 warning；实际归档哈希才是
迁移后的事实。该工具是一次性切换，不是兼容运行层。

## 缓存与资源

- `VIDEO_CONTENT_HOME/cache/media` 跨重试复用；
- 清单中的 `actual_bytes` / `actual_mib` 来自实际文件；
- OCR 与 ASR 默认串行使用 GPU；
- deep doctor 未验证前不得显式并行；
- 不完整重安装使用同一锁定计划恢复。

## Job 处理

- 技术失败：`retryable`，在 Profile 限额内退避重试；
- 登录失效：`paused_auth`，用户恢复可见登录后继续；
- 无音频、无可读文字或无法取得足够物理证据：`unprocessable`；
- 完成：所有请求且授权的产物均有哈希和验证结果。

不要通过删除 Job 目录“重试”；继续现有 Job，保留事件和 Artifact。

## 内容质量闸门

Watch Later 的 `source_faithful_full` Content 只有同时满足以下事实才算有效：

- 正文经过真实书面化，不是 cue 机械拼接、定长分段或只用正则补标点；
- Agent 实际抽查开头、中部和结尾，确认断句、口语噪声、转写错误和视觉指代已处理；
- `material_sections.items` 将每个实质章节的 Transcript cue 映射到成稿 block；
- 所有实质章节均为 `preserved`，省略项单独列出；
- Content media 与正文 image block 按顺序完全一致；
- 每个 `video_frame` 的 `visual_plan.block_index` 指向正文中的同一截图；
- 少于截图下限时，有静态来源侦察 Artifact 支持 `visual_exception`。

文章能渲染、图片 Artifact 存在或正文较长都不能替代这些验收。程序还组合检查正文与
Transcript 的长片段重合、标点密度和最长无标点片段；只有这些高风险信号同时出现时才报告
`raw Transcript passthrough`。它是防止明显假完成的硬停止，不是要求 Agent 为降低重合率而
改写。语义完整性和真实可读性仍由 Agent 对照完整 Transcript 判断。

## 真实运行中的常见假完成

遇到以下现象时，先按“哪一层的证据缺失”诊断，不要把结果直接交给下一层：

| 现象 | 不能据此推出 | 正确动作 |
| --- | --- | --- |
| 文章比视频短很多，细节和限定消失 | “已经完成了简洁改写” | 回到完整 Transcript，补回实质章节并重新做来源忠实审计 |
| 图片 Artifact 数量正确，但正文看不到截图 | “配图已经插入” | 检查有序 image block 和 `visual_plan.block_index`，错位就停在 Content |
| 保存后出现 Toast 或拿到 `appmsgid` | “草稿已可靠保存” | 刷新/重开同一草稿，回读正文、图片、封面、摘要和创作来源 |
| “内容由AI生成”点击过一次 | “平台声明已经生效” | 在刷新后的新快照中再次确认选中，再写入 Observation/Receipt |
| Browser Bridge/evaluate 一次超时 | “业务操作失败，可以新建” | 对同一目标重试可见快照；先查当前 Receipt，禁止重复建稿 |

文章过短、图片缺失和声明未回读不是同一种故障：前者是 Content 语义/结构问题，后两者是确定性
平台验收问题。不要用“下次注意”替代字段、验证器或 Skill 中的完成条件。

## 稍后再看

`watch_later_scan` 是一次调用。Profile 的 seen baseline 防止重排或旧视频再次入队。周期由
Codex automation 负责，仓库不运行后台 daemon。

## 微信

1. Content 审计和验证通过，Watch Later 稿件还必须通过书面化、完整章节与逐帧视觉计划检查；
2. 本轮明确授权保存草稿；
3. `wechat_prepare` 重建渲染包并准备瞬时剪贴板；修订已有草稿时显式使用 `replace_existing_draft=true`；
4. Browser Adapter 只观察可见编辑器，并确认新建目标或精确旧 `appmsgid`；
5. 填入正文、原视频封面和摘要，并按 Profile 选择“内容由AI生成”；
6. 只保存草稿，刷新同一草稿，回读正文、图片、封面、摘要和创作来源；
7. `wechat_bind` 生成并验证 Draft Receipt；修订时传入 `supersedes_receipt_id`，且 `appmsgid` 必须不变。

不保存 URL token、cookie、存储、原始 CDN URL 或剪贴板 HTML。AI 创作来源不是原创声明；任何
发布相关动作都不在范围。

### 微信交接的重试顺序

1. 先读取当前可见编辑器和数字 `appmsgid`；
2. 对同一目标刷新或重开并回读；
3. 只有在确认没有当前有效 Receipt 时才允许创建新草稿；
4. 明确修订只能原位更新同一 `appmsgid`，并以新 Receipt supersede 旧 Receipt；
5. 真实登录页才标记 `paused_auth`，普通读取超时保持 `retryable`。

## 验收层级

- `core`：Store、六产物、renderer、离线完整链路；
- `agent`：四个 Skill、MCP、Node adapter、打包边界；
- `media`：当前 FFmpeg/FFprobe 对授权 fixture 的真实探测；
- `live`：当前 Bilibili、OCR/ASR、Browser Bridge 和单独授权的微信编辑器。

编译或单元测试通过不能代替 live 结果。

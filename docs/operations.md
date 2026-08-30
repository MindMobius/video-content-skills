# 运行与诊断

## 先固定运行上下文

每次运行先确定三个值，并在同一轮中保持不变：

```text
config = .video-content/config.json
home   = config.values.home；未设置时使用 config.json 所在的 .video-content/
run_id = 本次扫描或处理的运行标识
```

从仓库根目录启动时，程序会自动发现 `.video-content/config.json`；直接 API 从仓库子目录启动时也会回到同一个仓库状态根。不要把临时目录当成新系统，也不要在没有加载同一份配置的情况下单独运行 `setup`、`doctor` 或证据服务。目录和生命周期规则见 [`docs/repository-layout.md`](repository-layout.md)。

结构变更或一次批处理结束后，先运行只读布局检查：

```powershell
python scripts/validate_layout.py
# 迁移或大规模整理后，追加完整数据校验
python scripts/validate_layout.py --integrity
```

只有 `ready=true` 且没有 residual/unexpected 项时，才开始下一轮处理。若 `historical_path_references.status=mapped`，表示历史 provenance 已登记，不需要也不允许改写旧 Artifact。

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
- 正文切换到来源叙述视角，不反复用“视频认为”“创作者指出”写成二手解说；
- `source_faithful_full` 保留实质内容，不是每个 cue；与主题无关的商品推广和平台 CTA 有
  omission，正文无占位说明；
- Agent 实际抽查开头、中部和结尾，确认断句、口语噪声、转写错误和视觉指代已处理；
- `material_sections.items` 将每个实质章节的 Transcript cue 映射到成稿 block；
- 所有实质章节均为 `preserved`，省略项单独列出；
- Content media 与正文 image block 按顺序完全一致；
- 每个 `video_frame` 的 `visual_plan.block_index` 指向正文中的同一截图；
- scout/contact sheet 只负责选时间点；最终 `video_frame` 通过 `source_frame_extract` 从
  `source_video` 重新生成，实际像素尺寸与元数据一致并保持来源显示画幅；
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
| 正文反复写“视频认为/创作者指出” | “来源已经声明，所以视角没问题” | 恢复来源直接叙述，只把必要归属和实际讨论对象保留下来 |
| 商品推广已删，却留下“原视频推广段”等标题 | “读者知道这里被删过就行” | 删除全部占位说明，在 `omissions` 内部记录 cue 范围和理由 |
| 图片 Artifact 数量正确，但正文看不到截图 | “配图已经插入” | 检查有序 image block 和 `visual_plan.block_index`，错位就停在 Content |
| 正文图统一是 640×360 / 960×540，放大后模糊或像固定画幅 | “微信自动压缩了图片” | 查 Artifact 来源；scout 只能选点，必须从 `source_video` 重新抽取最终帧并核对画幅 |
| DOCX 显示导入完成或正文出现了一部分 | “全文和全部图片已经进入微信” | 检查正文开头、中部、结尾以及图片数量、顺序、画幅和微信托管状态 |
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
3. `wechat_prepare` 重建渲染包并确定唯一目标；修订已有草稿时显式使用 `replace_existing_draft=true`；
4. 多图文章优先使用从最终 Content 派生、内嵌正文图片的 `article-import.docx` 和微信官方文档导入；富文本剪贴板只作后备，不能在状态不确定的同一编辑器里叠加；
5. Browser Adapter 只观察可见编辑器，并确认新建目标或精确旧 `appmsgid`；浏览器按当前登录状态与控制能力选择，`setFiles: Not allowed` 不能靠复制 DOCX 修复；
6. 导入后检查正文开头、中部、结尾以及图片数量、顺序、托管状态；有图时使用 Observation v3 比较天然宽高与显示宽高，拒绝画幅变化；
7. 填入准确标题、主动选择原视频封面和摘要，并按 Profile 选择“内容由AI生成”；
8. 只保存草稿，刷新同一草稿，回读正文、图片、封面、摘要和创作来源；
9. `wechat_bind` 生成并验证 Draft Receipt；修订时传入 `supersedes_receipt_id`，且 `appmsgid` 必须不变；批量任务只有当前 Job Receipt 有效后才进入下一 Job。

不把 URL token、cookie、存储、原始 CDN URL 或剪贴板 HTML 写入状态；DOCX 只保留在当前 Job
工作区，不另存为业务产物。AI 创作来源不是原创声明；任何发布相关动作都不在范围。

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

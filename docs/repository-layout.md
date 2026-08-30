# 仓库与运行时目录布局

本项目把**源码**和**运行数据**分开。Agent 只把源码提交到 Git，不把视频、字幕、截图、草稿回执或本机运行时混进源码目录。

## 源码仓库

```text
video-content-skills/
├─ .agents/skills/       唯一 canonical Skill 源
├─ docs/                 当前架构、运行规则和维护记录
├─ scripts/              bootstrap、迁移、验证和运行时安装入口
├─ src/video_content/    Python/MCP/CLI 实现
├─ tests/                离线契约与回归测试
├─ requirements/         Python/MCP 与重运行时锁定信息
├─ schemas/              持久产物和环境报告 Schema
└─ opencli-plugin/       OpenCLI 的只读稍后再看适配器
```

源码目录中不应出现：视频、音频、字幕、截图、浏览器快照、草稿正文、临时脚本、运行日志或本机依赖解压目录。

`docs/plans/` 只保存已经完成的设计/迁移记录，不是当前运行说明；遇到旧路径时以本页、`AGENTS.md`
和 `docs/operations.md` 为准。

## 唯一活动状态根

从仓库运行时，默认使用被 Git 忽略的 `.video-content/`：

```text
.video-content/
├─ config.json           唯一活动配置入口
├─ profiles/             Profile
├─ jobs/                 Job、Evidence、Transcript、Content、Receipt
├─ cache/media/          可跨重试复用的媒体缓存
├─ indexes/              幂等和查询索引
├─ locks/                并发锁
├─ meta/                 迁移、路径重定位和布局快照
│  ├─ migration-receipt.json
│  ├─ path-relocation.json
│  └─ state-layout.json
├─ runs/                 当前一次运行的临时工作目录
└─ archive/              已保留但不再参与运行的历史实验材料
```

只有 `profiles/`、`jobs/`、`cache/media/`、`indexes/` 和 `locks/` 是业务运行的核心目录；`meta/`、`runs/`、`archive/` 用于治理和生命周期管理，不能被 Agent 当成新的业务产品。迁移回执固定放在 `meta/migration-receipt.json`，不能重新写回状态根顶层。

历史 Artifact 中已经写入的绝对路径属于 provenance，不能为了“看起来新”而改写原始字节或哈希。状态根迁移后，`meta/path-relocation.json` 记录旧根到当前根/归档根的只读映射；诊断工具会把这类引用标成 `relocated` 或 `archived`，而不是误报成“依赖未安装”或“Artifact 丢失”。

`config.py` 会从命令行、环境变量和仓库本地 `.video-content/config.json` 自动解析配置。只要从仓库内启动，CLI、MCP 和直接 Python API 都应使用同一个配置上下文；没有显式 `home` 时，配置文件所在的 `.video-content/` 就是状态根锚点。没有可发现的仓库时，程序使用用户级配置目录，不会按当前子目录再创建一个状态根。不要再手工创建脱离配置的临时 Store。

## 归档与临时文件规则

- `.video-content/archive/` 是被 Git 忽略的本机历史归档区；旧运行时、旧状态和旧实验只放在这里，
  不回写活动状态。大型不可变运行时或迁移备份可以继续放在仓库外的
  `video-content-archive/`，但不能作为当前 `home`。两者都是历史区，不是第二个活动状态根；
  `meta/migration-receipt.json` 若指向外部归档，只表示历史迁移来源。
- 当前失败或待重试的运行放在 `.video-content/runs/<run_id>/`；任务结束后再清理或归档。
- `jobs/<job_id>/work/<content_id>/handoff-package/article-import.docx` 是从最终 Content
  派生的瞬时微信导入载体，可以按同一 Content 重新生成；它不是第七种业务产物，不进入源码仓库，
  也不能替代 Draft Receipt。
- 历史脚本、批处理预览和一次性分析结果放在 `.video-content/archive/<date>-<reason>/`，不放在状态根顶层。
- 不要在 `.video-content/` 顶层创建 `build-*`、`run-*`、`current-*`、`latest-*` 或散落的
  JSON/日志/截图。可复用代码放到仓库 `scripts/` 并配套测试；一次性工作放到当前 `runs/<run_id>/`。
- 顶层除 `config.json` 和上述固定目录外，不得新增自由命名文件或目录。迁移回执、布局快照和重定位登记都必须进入 `meta/`；当前已有的 `meta/state-layout.json` 是迁移时生成的只读快照。
- 仓库根目录也有明确的源代码白名单。新增顶层源码入口时，必须同时更新本页和
  `scripts/validate_layout.py`；临时产物、批次预览、日志和媒体文件不应通过“先放着”绕过这个约束。
- 需要隔离测试时显式传入 `--home <isolated-root>` 和 `--config <isolated-config>`，测试结束后删除或归档整个隔离根。

检查当前布局（只读，不会移动文件）：

```powershell
python scripts/validate_layout.py
# 迁移或大规模整理后，再做一次完整 Artifact 哈希校验
python scripts/validate_layout.py --integrity
```

输出中的 `historical_path_references` 是历史记录解释层：`mapped` 表示旧绝对路径已经有登记且能定位到当前或归档文件；它不是要把历史 Artifact 改写成新路径。

## Agent 启动顺序

```powershell
# 在仓库根目录执行；不需要猜路径
python scripts/bootstrap.py --apply --capability <required-capability>
.\.venv\Scripts\python.exe -m video_content.cli system doctor --capability <required-capability>
```

只有在 `doctor` 对所需能力报告 `ready` 后，才开始视频处理。若必须做隔离测试，应在报告中保留所用的 `config`、`home` 和 `run_id`，避免把“临时目录缺配置”误判成“本机缺依赖”。

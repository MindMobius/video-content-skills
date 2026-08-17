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

## 稍后再看

`watch_later_scan` 是一次调用。Profile 的 seen baseline 防止重排或旧视频再次入队。周期由
Codex automation 负责，仓库不运行后台 daemon。

## 微信

1. Content 审计和验证通过；
2. 本轮明确授权保存草稿；
3. `wechat_prepare` 重建渲染包并准备瞬时剪贴板；
4. Browser Adapter 只观察可见编辑器；
5. 保存草稿后刷新回读；
6. `wechat_bind` 生成并验证 Draft Receipt。

不保存 URL token、cookie、存储、原始 CDN URL 或剪贴板 HTML。任何发布相关动作都不在范围。

## 验收层级

- `core`：Store、六产物、renderer、离线完整链路；
- `agent`：四个 Skill、MCP、Node adapter、打包边界；
- `media`：当前 FFmpeg/FFprobe 对授权 fixture 的真实探测；
- `live`：当前 Bilibili、OCR/ASR、Browser Bridge 和单独授权的微信编辑器。

编译或单元测试通过不能代替 live 结果。

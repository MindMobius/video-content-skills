# 原视频画面选择

截图不是装饰，也不能用均匀时间间隔凑数量。它应帮助读者在离开视频后仍能理解原作者当时正在展示什么。

## 两阶段合同

画面侦察和正文交付是两个不同阶段：

1. `scout`、联系表和低清候选帧只用于判断“哪个时间点值得看”；
2. 时间点确定后，必须从当前 Job 的 `source_video` 重新抽取最终帧；
3. Agent 查看最终帧本身，确认清晰度、画面内容和正文位置后，才把它加入 Content。

`ocr_scout_contact_sheet`、`ocr_scout_plan`、`work/agent-media/scout/` 中的图片以及任何固定为
`640×360`、`960×540` 的预览图都不能直接晋升为正文 `video_frame`。即使预览图“看起来够用”，
它仍然只是选点工具。

## 选择与生成

1. 从完整 Transcript 和临时来源地图中标记必须结合画面理解的演示、图表、对比、人物变化、案例切换和关键场景。
2. 为每个节点记录目标时间范围，而不是先决定截图数量。
3. 在目标点前后查看候选帧，排除黑屏、转场、重复画面、遮挡、无意义大字幕和与正文不对应的帧。
4. 确定时间点后，调用 MCP `source_frame_extract`，或运行：

   ```text
   video-content media extract-frame <job_id> <timestamp_ms> --selection-reason <具体理由>
   ```

   该入口只读取 Job 的 `source_video`，不会把 scout/contact sheet 当成输入。
5. 查看返回的最终 Artifact，确认画面与选择理由一致，没有模糊放大、错误裁切、黑边填充或人物/字幕变形。
6. 将最终帧放在对应段落之后或论述切换处，不把全部图片堆在开头。
7. 在 Content audit 的 `visual_plan` 中记录 `artifact_id`、`timestamp_ms`、实际 `block_index` 和具体使用理由。验证器会确认该索引确实指向正文中的同一张 `video_frame`。

仅把截图 Artifact 填进 Content 的 media 列表不算完成；它必须作为 image block 真正出现在正文中。
截图全部堆在开头、结尾或连续排列，也不能替代“放在对应论述附近”的 Agent 语义检查。

## 画幅与清晰度合同

- 最终帧必须声明 `extraction_role=final`、`extraction_method=ffmpeg_source_frame` 和
  `resolution_policy=source_display_native`，并绑定当前 `source_video` 的 Artifact ID 与 SHA-256。
- 抽帧使用来源的显示画幅：`scale=w=round(iw*sar):h=ih:flags=lanczos,setsar=1`。普通方形像素视频
  保持原像素尺寸；非方形像素只做显示画幅校正；横屏、竖屏和方形视频都保持各自比例。
- 不允许为了统一外观同时固定宽和高，不允许强制裁成 16:9，也不允许先缩成通用缩略图再放大。
  `640×360` 本身不一定错误——来源真的只有这个分辨率时可以保留；错误的是无论来源尺寸如何都先降到固定预览规格。
- Artifact 元数据中的 `pixel_width` / `pixel_height` 必须与实际图片字节一致，
  `display_aspect_preserved=true`。`source_faithful_full` 会拒绝 scout 帧、伪造尺寸或未绑定来源视频的帧。
- DOCX 或平台显示可以限制最大宽度，但高度必须按图片比例自动计算；不得同时强制固定高度。

## 数量边界

Profile 的 `minimum_source_frames` 只是防止“只有封面”的最低门槛。普通视频通常需要覆盖 3 至 5 个实质节点；长视频、访谈、教程或视觉演示应按内容自然增加。若侦察证据证明来源是静态播客封面或没有足够实质画面变化，不得复制相同截图凑数；在 audit 中写入经 Agent 批准的 `visual_exception`，并引用 `ocr_scout_contact_sheet` 或 `ocr_scout_plan` Artifact。除此之外，少于 Profile 下限不能通过验证。

封面仍使用原视频封面。未经单独授权，不生成插画、不抓取图库图片，也不使用与来源无关的填充视觉。

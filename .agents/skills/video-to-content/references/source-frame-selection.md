# 原视频画面选择

截图不是装饰，也不能用均匀时间间隔凑数量。它应帮助读者在离开视频后仍能理解原作者当时正在展示什么。

## 选择流程

1. 从完整 Transcript 和临时来源地图中标记必须结合画面理解的演示、图表、对比、人物变化、案例切换和关键场景。
2. 为每个节点记录目标时间范围，而不是先决定截图数量。
3. 在目标点前后抽取多个候选帧，制作联系表或逐张查看。
4. 排除黑屏、转场、重复画面、遮挡、无意义大字幕和与正文不对应的帧。
5. 用 FFmpeg 保存原视频帧，通过 `Store.put_artifact(kind="video_frame", metadata={"timestamp_ms": ...})` 注册。
6. 将帧放在对应段落之后或论述切换处，不把全部图片堆在开头。
7. 在 Content audit 的 `visual_plan` 中记录 `artifact_id`、`timestamp_ms`、实际 `block_index` 和具体使用理由。验证器会确认该索引确实指向正文中的同一张 `video_frame`。

仅把截图 Artifact 填进 Content 的 media 列表不算完成；它必须作为 image block 真正出现在正文中。
截图全部堆在开头、结尾或连续排列，也不能替代“放在对应论述附近”的 Agent 语义检查。

## 数量边界

Profile 的 `minimum_source_frames` 只是防止“只有封面”的最低门槛。普通视频通常需要覆盖 3 至 5 个实质节点；长视频、访谈、教程或视觉演示应按内容自然增加。若侦察证据证明来源是静态播客封面或没有足够实质画面变化，不得复制相同截图凑数；在 audit 中写入经 Agent 批准的 `visual_exception`，并引用 `ocr_scout_contact_sheet` 或 `ocr_scout_plan` Artifact。除此之外，少于 Profile 下限不能通过验证。

封面仍使用原视频封面。未经单独授权，不生成插画、不抓取图库图片，也不使用与来源无关的填充视觉。

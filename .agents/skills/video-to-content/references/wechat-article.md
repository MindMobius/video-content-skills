# 微信公众号文章载体

微信公众号只是载体，不是新的作者。`carrier=wechat_article` 默认应呈现视频的来源忠实书面版，
不能因为平台支持标题、摘要、小标题和图片，就重新发明主题、文风或论证结构。正文直接采用来源
叙述视角，不写成“这条视频说了什么”的二手解说稿。

使用克制的 manuscript：

```json
{
  "schema_version": "video-content/wechat-manuscript-v1",
  "title": "...",
  "summary": "...",
  "source": {
    "title": "...",
    "creator": "...",
    "canonical_url": "https://www.bilibili.com/video/..."
  },
  "blocks": [
    {
      "type": "image",
      "artifact_id": "art_...",
      "source_kind": "video_cover"
    },
    {"type": "lead", "text": "..."},
    {"type": "heading", "text": "..."},
    {"type": "paragraph", "text": "..."},
    {
      "type": "image",
      "artifact_id": "art_...",
      "source_kind": "video_frame",
      "timestamp_ms": 42000
    }
  ]
}
```

## 载体规则

- 标题默认保留原题或做不增强主张的最小适配；
- lead 和 summary 说明来源实际讨论范围，不代替作者得出新结论；
- 来源声明集中在 manuscript `source`、署名区或一次简短披露中，正文不反复使用“视频认为”作为叙述壳；
- 小标题来自原视频已有章节、问题或明显转场；
- 不把访谈、调查或教程机械改成公众号列表文；
- 正文保持来源的人物身份、观点顺序、专业密度、第一人称和语气；当“视频”是实际讨论对象时照常保留；
- 与主题无关的广告、商品推广和平台 CTA 作为 omission 清除，不输出任何占位标题或删除说明；
- 来源披露保留原标题、创作者和 canonical URL；必要的赞助或利益披露不得因删广告而消失。

允许的图片来源只有 `video_cover` 和 `video_frame`；frame 必须包含 `timestamp_ms`，并放在来源
使用该画面或论证的对应位置。第一方 renderer 复制来源资产，生成不含 `<img>` 的干净正文
HTML，并为 handoff adapter 保留单行相对图片标记。

Renderer 成功不代表来源忠实审计通过，也不授权保存微信草稿。

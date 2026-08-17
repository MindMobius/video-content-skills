# WeChat article carrier

Use `carrier=wechat_article` and a restrained manuscript:

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

Allowed image sources are `video_cover` and `video_frame`; a frame requires
`timestamp_ms`. The first-party renderer copies source assets, emits clean body
HTML without `<img>` elements, and leaves one-line relative markers for the
handoff adapter. Renderer success is not fidelity approval and not draft-save
authorization.

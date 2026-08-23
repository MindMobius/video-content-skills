export const MOCK_EDITOR_VERSION = '1'

export function createEditorState() {
  return {
    schema_version: 'video-content/mock-wechat-editor-v1',
    version: MOCK_EDITOR_VERSION,
    title: '',
    summary: '',
    body_html: '',
    body_images: [],
    cover: null,
    required_creation_source: null,
    creation_source: { type: 'ai_generated', declared: false },
    appmsgid: null,
    save_history: [],
    saved: false,
    published: false,
  }
}

export function pasteArticle(state, article) {
  if (state.saved) throw new Error('Create a new editor state before replacing a saved draft')
  if (!article.title || !article.body_html) throw new Error('Title and body HTML are required')
  const imageCount = Number(article.image_count || 0)
  return {
    ...state,
    title: article.title,
    summary: article.summary || '',
    body_html: article.body_html,
    required_creation_source: article.required_creation_source || null,
    body_images: Array.from({ length: imageCount }, (_, index) => ({
      index: index + 1,
      visible: true,
      complete: true,
      natural_width: 1280,
      width: 640,
      height: 360,
      host_class: 'wechat',
    })),
  }
}

export function selectCover(state, imageIndex = 1) {
  const image = state.body_images.find(item => item.index === Number(imageIndex))
  if (!image) throw new Error('Cover must reference an imported body image')
  return {
    ...state,
    cover: {
      source: `body_image_${image.index}`,
      asset: `assets/${String(image.index).padStart(2, '0')}-cover.jpg`,
      selected: true,
      crop_confirmed: true,
      wechat_hosted_preview: image.host_class === 'wechat',
    },
  }
}

export function declareAiGenerated(state) {
  return {
    ...state,
    creation_source: { type: 'ai_generated', declared: true },
  }
}

export function saveDraft(state, timestamp = '2026-01-01T00:00:00Z') {
  if (!state.title || !state.body_html || !state.cover) {
    throw new Error('Title, body, and cover are required before saving')
  }
  if (state.required_creation_source === 'ai_generated' && state.creation_source.declared !== true) {
    throw new Error('AI-generated creation source must be declared before saving')
  }
  const nextHistory = [...state.save_history, `${timestamp} manual_save`]
  return {
    ...state,
    appmsgid: state.appmsgid || '100000001',
    save_history: nextHistory,
    saved: true,
    published: false,
  }
}

export function readBack(state) {
  return structuredClone(state)
}

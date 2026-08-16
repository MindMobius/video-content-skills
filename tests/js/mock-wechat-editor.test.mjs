import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createEditorState,
  pasteArticle,
  readBack,
  saveDraft,
  selectCover,
} from '../fixtures/mock-wechat-editor/mock-editor-model.mjs'

test('mock editor covers paste, image ingestion, cover, save, and read-back', () => {
  let state = createEditorState()
  state = pasteArticle(state, {
    title: '验收文章',
    summary: '验收摘要',
    body_html: '<p>正文</p>',
    image_count: 2,
  })
  state = selectCover(state, 1)
  state = saveDraft(state, '2026-08-16T08:00:00Z')
  const readback = readBack(state)

  assert.equal(readback.title, '验收文章')
  assert.equal(readback.body_images.length, 2)
  assert.equal(readback.body_images.every(item => item.host_class === 'wechat'), true)
  assert.equal(readback.cover.wechat_hosted_preview, true)
  assert.equal(readback.appmsgid, '100000001')
  assert.equal(readback.save_history.length, 1)
  assert.equal(readback.saved, true)
  assert.equal(readback.published, false)
})

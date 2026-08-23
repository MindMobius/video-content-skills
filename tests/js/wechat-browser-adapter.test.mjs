import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ADAPTER_VERSION,
  classifyImageSource,
  parseAppmsgId,
  summarizeBodyImages,
  summarizeCreationSource,
} from '../../.agents/skills/wechat-draft/scripts/browser-adapter.js'

test('extracts only appmsgid from a token-bearing URL', () => {
  const value = 'https://mp.weixin.qq.com/cgi-bin/appmsg?action=edit&appmsgid=100000721&token=do-not-return'
  assert.equal(parseAppmsgId(value), '100000721')
  assert.equal(ADAPTER_VERSION, '2')
})

test('classifies WeChat, transient, and external image sources', () => {
  assert.equal(classifyImageSource('https://mmbiz.qpic.cn/example.jpg'), 'wechat')
  assert.equal(classifyImageSource('data:image/png;base64,AAAA'), 'transient')
  assert.equal(classifyImageSource('assets/01-cover.jpg'), 'transient')
  assert.equal(classifyImageSource('https://example.com/image.jpg'), 'other')
})

test('normalizes image descriptors without retaining source URLs', () => {
  const result = summarizeBodyImages([
    {
      visible: true,
      complete: true,
      natural_width: 1280,
      width: 640,
      height: 360,
      source: 'https://mmbiz.qpic.cn/example.jpg',
    },
  ], 1, 0)

  assert.equal(result.items[0].host_class, 'wechat')
  assert.equal(Object.hasOwn(result.items[0], 'source'), false)
  assert.equal(result.intended, 1)
})

test('requires one visibly selected AI-generated declaration', () => {
  const selected = summarizeCreationSource([
    { visible: true, label: '内容由AI生成', selected: true },
    { visible: true, label: '未声明', selected: false },
  ])
  assert.deepEqual(selected, {
    type: 'ai_generated',
    declared: true,
    visible_candidates: 1,
    selected_candidates: 1,
  })

  const missing = summarizeCreationSource([
    { visible: true, label: '内容由AI生成', selected: false },
  ])
  assert.equal(missing.declared, false)
  assert.equal(missing.selected_candidates, 0)
})

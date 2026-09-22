import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ADAPTER_VERSION,
  collectHandoffSnapshot,
  classifyImageSource,
  parseAppmsgId,
  summarizeBodyImages,
  summarizeCoverEvidence,
  summarizeCreationSource,
  summarizeDraftListCover,
} from '../../.agents/skills/wechat-draft/scripts/browser-adapter.js'

test('extracts only appmsgid from a token-bearing URL', () => {
  const value = 'https://mp.weixin.qq.com/cgi-bin/appmsg?action=edit&appmsgid=100000721&token=do-not-return'
  assert.equal(parseAppmsgId(value), '100000721')
  assert.equal(ADAPTER_VERSION, '4')
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
      natural_height: 720,
      width: 640,
      height: 360,
      source: 'https://mmbiz.qpic.cn/example.jpg',
    },
    {
      visible: false,
      complete: true,
      natural_width: 0,
      natural_height: 0,
      width: 0,
      height: 0,
      source: '',
    },
  ], 1, 0)

  assert.equal(result.items.length, 1)
  assert.equal(result.items[0].host_class, 'wechat')
  assert.equal(result.items[0].natural_height, 720)
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


test('rejects a hidden cover preview even when CSS has a background image', () => {
  const result = summarizeCoverEvidence(
    { visible: false, background_present: true, width: 0, height: 0 },
    {
      list_thumbnail_read_back: false,
      persistent_media_present: false,
      crop_data_present: false,
    },
    true,
  )

  assert.equal(result.selected, false)
  assert.equal(result.editor_visible_after_refresh, false)
  assert.equal(result.rendered_width, 0)
})

test('requires the same draft card to expose durable cover fields', () => {
  const listState = summarizeDraftListCover({
    app_id: 100000721,
    img_url: 'present',
    multi_item: [{
      cover: 'present',
      cdn_url: 'present',
      cdn_1_1_url: 'present',
      cdn_235_1_url: 'present',
      crop_list: '{persisted}',
    }],
  }, '100000721')
  const cover = summarizeCoverEvidence(
    { visible: true, background_present: true, width: 235, height: 100 },
    listState,
    true,
  )

  assert.deepEqual(listState, {
    same_draft: true,
    list_thumbnail_read_back: true,
    persistent_media_present: true,
    crop_data_present: true,
  })
  assert.equal(cover.selected, true)
  assert.equal(cover.list_thumbnail_read_back, true)
  assert.equal(cover.persistent_media_present, true)
  assert.equal(cover.crop_data_present, true)
})


function handoffFixture() {
  const element = (text = '', extra = {}) => ({
    innerText: text, textContent: text, innerHTML: text, style: {},
    getBoundingClientRect: () => ({ width: 640, height: 360 }),
    querySelectorAll: () => [], ...extra,
  })
  const body = element('上一份文档的正文')
  const entries = new Map([
    ['.ProseMirror', [body]], ['#account', [element('正确账号')]],
    ['#title', [element('', { value: '文章标题' })]],
    ['#js_description', [element('', { value: '摘要' })]],
    ['#author', [element('', { value: '' })]],
    ['#original', [element('未声明')]],
  ])
  const options = {
    document: { querySelectorAll: selector => entries.get(selector) || [] },
    locationHref: 'https://mp.weixin.qq.com/cgi-bin/appmsg?type=77&isNew=1&token=never-export',
    browserId: 'actual-browser', tabId: 'actual-tab', accountSelector: '#account',
    originalSelector: '#original', importBusySelector: '#busy',
  }
  return { options, entries, element, body }
}

test('handoff snapshots report actual old body, never infer import success from its length', () => {
  const { options } = handoffFixture()
  const first = collectHandoffSnapshot(options)
  const next = collectHandoffSnapshot(options)
  assert.equal(first.ready, true)
  assert.equal(first.body_text, '上一份文档的正文')
  assert.notEqual(first.snapshot_id, next.snapshot_id)
  assert.equal(first.target.document_id, next.target.document_id)
  assert.equal(first.target.account_name, '正确账号')
  assert.equal(first.editor_type, '77')
  assert.equal(Object.hasOwn(first, 'import_success'), false)
  assert.equal(JSON.stringify(first).includes('never-export'), false)
  assert.equal(JSON.stringify(first).includes('https://'), false)
})

test('missing or ambiguous controls stay unknown, not passed', () => {
  const { options, entries, element } = handoffFixture()
  delete options.importBusySelector
  entries.delete('#original')
  entries.set('#account', [element('账号一'), element('账号二')])
  const snapshot = collectHandoffSnapshot(options)
  assert.equal(snapshot.ready, false)
  assert.equal(snapshot.import_busy, null)
  assert.equal(snapshot.original_declared, null)
  assert.equal(snapshot.target.account_name, '')
  assert.equal(snapshot.cover.selected, false)
})

test('list page and visible error dialog cannot masquerade as import completion', () => {
  const { options, entries, element } = handoffFixture()
  options.locationHref = 'https://mp.weixin.qq.com/cgi-bin/home?token=never-export'
  entries.set('.weui-desktop-dialog__wrp', [element('文档导入出错')])
  const snapshot = collectHandoffSnapshot(options)
  assert.equal(snapshot.page_kind, 'other')
  assert.deepEqual(snapshot.dialogs, ['文档导入出错'])
})

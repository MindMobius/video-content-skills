export const ADAPTER_ID = 'video-content/wechat-browser-adapter'
export const ADAPTER_VERSION = '4'

const WECHAT_IMAGE_HOSTS = new Set(['mmbiz.qpic.cn', 'mmbiz.qlogo.cn'])

export function parseAppmsgId(value) {
  try {
    const parsed = new URL(value, 'https://mp.weixin.qq.com/')
    const candidate = parsed.searchParams.get('appmsgid')
    return candidate && /^\d+$/.test(candidate) ? candidate : null
  } catch {
    return /^\d+$/.test(String(value).trim()) ? String(value).trim() : null
  }
}

export function classifyImageSource(value) {
  if (!value) return 'empty'
  const source = String(value).trim()
  if (/^(data:|file:|blob:)/i.test(source) || !source.includes('://')) return 'transient'
  try {
    return WECHAT_IMAGE_HOSTS.has(new URL(source).hostname.toLowerCase()) ? 'wechat' : 'other'
  } catch {
    return 'other'
  }
}

export function summarizeBodyImages(items, intended, localPathMarkersRemaining = 0) {
  const normalized = items
    .map(item => ({
      visible: item.visible === true,
      complete: item.complete === true,
      natural_width: Number(item.natural_width || 0),
      natural_height: Number(item.natural_height || 0),
      width: Number(item.width || 0),
      height: Number(item.height || 0),
      host_class: item.host_class || classifyImageSource(item.source),
    }))
    .filter(item => item.natural_width > 0 || item.natural_height > 0 || item.width > 0 || item.height > 0)
  return {
    intended: Number(intended),
    items: normalized,
    local_path_markers_remaining: Number(localPathMarkersRemaining),
  }
}

export function summarizeCreationSource(items, expectedLabel = '内容由AI生成') {
  const candidates = items.filter(item =>
    item.visible === true && String(item.label || '').includes(expectedLabel)
  )
  const selected = candidates.filter(item => item.selected === true)
  return {
    type: 'ai_generated',
    declared: candidates.length === 1 && selected.length === 1,
    visible_candidates: candidates.length,
    selected_candidates: selected.length,
  }
}

export function describeCoverPreview(element) {
  if (!element) {
    return { visible: false, background_present: false, width: 0, height: 0 }
  }
  const rect = element.getBoundingClientRect()
  const style = element.ownerDocument?.defaultView?.getComputedStyle(element)
  return {
    visible: isVisible(element),
    background_present: Boolean(style?.backgroundImage && style.backgroundImage !== 'none'),
    width: Number(rect.width || 0),
    height: Number(rect.height || 0),
  }
}

export function summarizeDraftListCover(item, expectedAppmsgid) {
  const primary = item?.multi_item?.[0] || {}
  const sameDraft = String(item?.app_id || '') === String(expectedAppmsgid || '')
  const cropValue = String(primary.crop_list || '')
  const emptyCrop = '{&quot;crop_list&quot;:[],&quot;crop_list_percent&quot;:[]}'
  return {
    same_draft: sameDraft,
    list_thumbnail_read_back: sameDraft && Boolean(primary.cover && item?.img_url),
    persistent_media_present: sameDraft && Boolean(
      primary.cover && primary.cdn_url && primary.cdn_1_1_url &&
      primary.cdn_235_1_url && item?.img_url
    ),
    crop_data_present: sameDraft && Boolean(cropValue && cropValue !== emptyCrop),
  }
}

export function summarizeCoverEvidence(preview, listState, cropConfirmed = false) {
  const width = Number(preview?.width || 0)
  const height = Number(preview?.height || 0)
  const visible = preview?.visible === true && width > 0 && height > 0
  return {
    selected: visible && preview?.background_present === true,
    crop_confirmed: cropConfirmed === true,
    editor_visible_after_refresh: visible,
    rendered_width: width,
    rendered_height: height,
    list_thumbnail_read_back: listState?.list_thumbnail_read_back === true,
    persistent_media_present: listState?.persistent_media_present === true,
    crop_data_present: listState?.crop_data_present === true,
  }
}

export function collectWechatEditorState(options = {}) {
  const documentObject = options.document || globalThis.document
  const locationValue = options.locationHref || globalThis.location?.href || ''
  if (!documentObject) throw new Error('A live document is required')
  const bodySelector = options.bodySelector || '[contenteditable="true"]'
  const bodyCandidates = visibleElements(documentObject.querySelectorAll(bodySelector))
  if (bodyCandidates.length !== 1) {
    return {
      schema_version: 'video-content/wechat-browser-snapshot-v1',
      adapter: { id: ADAPTER_ID, version: ADAPTER_VERSION },
      ready: false,
      ambiguity: { body_candidates: bodyCandidates.length },
      appmsgid: parseAppmsgId(locationValue),
    }
  }
  const body = bodyCandidates[0]
  const markerSelector = options.markerSelector || '[data-local-image-slot]'
  const images = [...body.querySelectorAll('img')].map(imageDescriptor)
  return {
    schema_version: 'video-content/wechat-browser-snapshot-v1',
    adapter: { id: ADAPTER_ID, version: ADAPTER_VERSION },
    ready: true,
    appmsgid: parseAppmsgId(locationValue),
    body_images: summarizeBodyImages(
      images,
      options.intendedImages ?? images.length,
      visibleElements(body.querySelectorAll(markerSelector)).length,
    ),
    fields: {
      title: visibleFieldValue(documentObject, options.titleSelector || '#title, textarea[name="title"]'),
      summary: visibleFieldValue(documentObject, options.summarySelector || 'textarea[name="digest"], #js_description'),
      author: visibleFieldValue(documentObject, options.authorSelector || '#author, input[name="author"]'),
    },
    ...(options.creationSourceSelector ? {
      creation_source: summarizeCreationSource(
        [...documentObject.querySelectorAll(options.creationSourceSelector)].map(creationSourceDescriptor),
        options.creationSourceLabel || '内容由AI生成',
      ),
    } : {}),
  }
}

function creationSourceDescriptor(element) {
  const control = element.matches?.('input, [role="checkbox"], [role="radio"], [role="option"]')
    ? element
    : element.querySelector?.('input, [role="checkbox"], [role="radio"], [role="option"]') || element
  const ariaChecked = control.getAttribute?.('aria-checked')
  const ariaSelected = control.getAttribute?.('aria-selected')
  return {
    visible: isVisible(element),
    label: element.innerText || element.textContent || element.getAttribute?.('aria-label') || '',
    selected: control.checked === true || control.selected === true || ariaChecked === 'true' || ariaSelected === 'true',
  }
}

function imageDescriptor(element) {
  const rect = element.getBoundingClientRect()
  return {
    visible: isVisible(element),
    complete: element.complete === true,
    natural_width: Number(element.naturalWidth || 0),
    natural_height: Number(element.naturalHeight || 0),
    width: Number(rect.width || 0),
    height: Number(rect.height || 0),
    host_class: classifyImageSource(element.currentSrc || element.src || ''),
  }
}

function visibleFieldValue(documentObject, selector) {
  const candidates = visibleElements(documentObject.querySelectorAll(selector))
  if (candidates.length !== 1) return { value: null, visible_candidates: candidates.length }
  const element = candidates[0]
  return { value: element.value ?? element.textContent ?? '', visible_candidates: 1 }
}

function visibleElements(elements) {
  return [...elements].filter(isVisible)
}

function isVisible(element) {
  const style = globalThis.getComputedStyle ? globalThis.getComputedStyle(element) : element.style || {}
  const rect = element.getBoundingClientRect()
  return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity ?? 1) > 0 && rect.width > 0 && rect.height > 0
}



// Read-only snapshot for the Python handoff gate. Selectors must come from the
// current visible editor; absent/ambiguous controls stay unknown, not "passed".
export function collectHandoffSnapshot(options = {}) {
  const doc = options.document || globalThis.document
  if (!doc) throw new Error('A live document is required')
  const url = new URL(options.locationHref || globalThis.location?.href || 'about:blank')
  const one = selector => {
    if (!selector) return null
    const matches = visibleElements(doc.querySelectorAll(selector))
    return matches.length === 1 ? matches[0] : null
  }
  const body = one(options.bodySelector || '.ProseMirror')
  const account = one(options.accountSelector)
  const title = one(options.titleSelector || '#title')
  const summary = one(options.summarySelector || '#js_description')
  const author = one(options.authorSelector || '#author')
  const original = one(options.originalSelector)
  const originalText = original ? String(original.innerText || original.textContent || '').trim() : null
  const fields = { value: element => element ? (element.value ?? element.innerText ?? element.textContent ?? '') : null }
  const dialogs = visibleElements(doc.querySelectorAll(options.dialogSelector || '.weui-desktop-dialog__wrp'))
    .map(element => String(element.innerText || element.textContent || '').trim())
  const source = options.creationSourceSelector ? summarizeCreationSource(
    [...doc.querySelectorAll(options.creationSourceSelector)].map(creationSourceDescriptor),
  ) : null
  const images = body ? summarizeBodyImages([...body.querySelectorAll('img')].map(imageDescriptor), 0).items : []
  const html = body?.innerHTML || ''
  const cover = summarizeCoverEvidence(
    describeCoverPreview(one(options.coverSelector || '#js_cover_area .js_cover_preview_new')),
    options.draftListCover, options.cropConfirmed === true,
  )
  return {
    snapshot_id: globalThis.crypto.randomUUID().replaceAll('-', ''),
    observed_at: Date.now(),
    target: {
      browser_id: options.browserId || '', tab_id: String(options.tabId || ''),
      document_id: String(globalThis.performance.timeOrigin),
      account_name: String(account?.innerText || account?.textContent || '').trim(),
    },
    ready: Boolean(body && title && summary && account),
    page_kind: url.href === 'about:blank' ? 'blank' : url.hostname === 'mp.weixin.qq.com' && url.pathname === '/cgi-bin/appmsg' && body ? 'editor' : 'other',
    editor_type: url.searchParams.get('type'),
    appmsgid: parseAppmsgId(url.href),
    body_text: readEditorBodyText(body),
    images,
    local_path_markers_remaining: (html.match(/data-local-image-slot|file:\/\/|src=["']assets\//g) || []).length,
    import_busy: options.importBusySelector ? visibleElements(doc.querySelectorAll(options.importBusySelector)).length > 0 : null,
    dialogs,
    import_error: options.importErrorSelector ? String(one(options.importErrorSelector)?.innerText || '') : '',
    title: fields.value(title), summary: fields.value(summary), author: fields.value(author),
    original_declared: originalText === null ? null : !originalText.includes('未声明'),
    cover,
    draft_list_appmsgid: options.draftListCover?.same_draft ? String(options.draftListAppmsgid || '') : null,
    creation_source: { selected_count: source?.declared ? source.selected_candidates : 0, label: source?.declared ? '内容由AI生成' : '' },
  }
}

// Legacy recovery only: read the full unfiltered list, never mutate the platform.
export function collectDraftListSnapshot(options = {}) {
  const doc = options.document || globalThis.document
  const url = new URL(globalThis.location.href)
  const accounts = visibleElements(doc.querySelectorAll(options.accountSelector))
  const data = globalThis.wx?.cgiData
  const text = String(doc.body?.innerText || '')
  const normalize = value => String(value).replace(/\s+/g, '')
  const rows = Array.isArray(data?.item) ? data.item : []
  return {
    snapshot_id: globalThis.crypto.randomUUID().replaceAll('-', ''),
    observed_at: Date.now(),
    target: { browser_id: options.browserId || '', tab_id: String(options.tabId || ''),
      document_id: String(globalThis.performance.timeOrigin),
      account_name: accounts.length === 1 ? accounts[0].innerText.trim() : '' },
    ready: accounts.length === 1 && Array.isArray(data?.item),
    page_kind: url.hostname === 'mp.weixin.qq.com' && url.pathname === '/cgi-bin/appmsg' && url.searchParams.get('action') === 'list_card' ? 'draft_list' : 'other',
    editor_type: url.searchParams.get('type'),
    unfiltered: Number(data?.begin) === 0 && !data?.query && !url.searchParams.get('query'),
    loaded_all: text.includes('已加载全部内容') && rows.length === Number(data?.file_cnt?.draft_count),
    total: Number(data?.file_cnt?.draft_count ?? -1),
    entries: rows.map(item => ({ appmsgid: String(item.app_id), title: String(item.title || ''),
      created_at_epoch: Number(item.create_time),
      title_visible: Boolean(item.title) && normalize(text).includes(normalize(item.title)) })),
  }
}

export function readEditorBodyText(body) {
  if (!body) return null
  if (!body.cloneNode) return body.innerText ?? body.textContent ?? null
  const copy = body.cloneNode(true)
  for (const node of copy.querySelectorAll('.editor_content_placeholder.ProseMirror-widget[contenteditable="false"]')) node.remove()
  return copy.textContent || ""
}

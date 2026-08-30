export const ADAPTER_ID = 'video-content/wechat-browser-adapter'
export const ADAPTER_VERSION = '3'

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


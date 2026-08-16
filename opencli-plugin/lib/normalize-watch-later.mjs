const canonicalUrl = (bvid) => `https://www.bilibili.com/video/${bvid}/`

export class BilibiliWatchLaterError extends Error {
  constructor(code, message, { authRequired = false, retryable = false } = {}) {
    super(message)
    this.name = 'BilibiliWatchLaterError'
    this.code = code
    this.authRequired = authRequired
    this.retryable = retryable
  }
}

export function normalizeWatchLaterPayload(payload, limit = 100) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('Malformed Bilibili Watch Later response')
  }
  const httpStatus = Number(payload.__http ?? 200)
  const riskControlled = httpStatus === 403
    || httpStatus === 412
    || payload.code === -352
    || payload.data?.v_voucher != null
  if (riskControlled) {
    const detail = httpStatus === 403 || httpStatus === 412
      ? `HTTP ${httpStatus}`
      : `API code ${payload.code}`
    throw new BilibiliWatchLaterError(
      'BILIBILI_RISK_CONTROL',
      `Bilibili risk control triggered (${detail})`,
      { retryable: true },
    )
  }
  if (payload.code === -101) {
    throw new BilibiliWatchLaterError(
      'BILIBILI_AUTH_REQUIRED',
      'Bilibili login required',
      { authRequired: true },
    )
  }
  if (payload.code !== 0) {
    throw new BilibiliWatchLaterError(
      'BILIBILI_API_ERROR',
      `Bilibili Watch Later failed: ${payload.message ?? payload.code}`,
    )
  }
  const list = payload.data?.list
  if (!Array.isArray(list)) {
    throw new Error('Malformed Bilibili Watch Later list')
  }
  const bounded = Math.max(1, Math.min(Number(limit) || 100, 100))
  return list.slice(0, bounded).map((item, index) => {
    const bvid = String(item?.bvid ?? '').trim()
    if (!/^BV[A-Za-z0-9]+$/.test(bvid)) {
      throw new Error('Malformed Bilibili Watch Later BVID')
    }
    const pageValue = Number(item?.page?.page ?? item?.page ?? 1)
    if (!Number.isSafeInteger(pageValue) || pageValue < 1) {
      throw new Error('Malformed Bilibili Watch Later page')
    }
    const addedSeconds = Number(item?.add_at ?? 0)
    return {
      bvid,
      page: pageValue,
      title: String(item?.title ?? ''),
      url: canonicalUrl(bvid),
      position: index + 1,
      addedAt: Number.isFinite(addedSeconds) && addedSeconds > 0
        ? new Date(addedSeconds * 1000).toISOString()
        : null,
    }
  })
}

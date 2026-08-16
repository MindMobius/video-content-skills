import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeWatchLaterPayload } from '../../opencli-plugin/lib/normalize-watch-later.mjs'

const payload = {
  code: 0,
  message: '0',
  data: {
    list: [
      {
        bvid: 'BV1alpha',
        title: 'Alpha',
        add_at: 1786838400,
        page: { page: 2 },
        owner: { name: 'private owner field' },
      },
    ],
  },
}

test('normalizes a Watch Later provider payload to stable fields', () => {
  const rows = normalizeWatchLaterPayload(payload, 100)
  assert.deepEqual(rows, [
    {
      bvid: 'BV1alpha',
      page: 2,
      title: 'Alpha',
      url: 'https://www.bilibili.com/video/BV1alpha/',
      position: 1,
      addedAt: '2026-08-16T00:00:00.000Z',
    },
  ])
  assert.equal(JSON.stringify(rows).includes('owner'), false)
})

test('classifies login, risk control, and malformed responses', () => {
  assert.throws(
    () => normalizeWatchLaterPayload({ code: -101, message: 'not logged in' }),
    (error) => {
      assert.equal(error.code, 'BILIBILI_AUTH_REQUIRED')
      assert.equal(error.authRequired, true)
      return /login/i.test(error.message)
    },
  )
  for (const payload of [
    { code: -352, message: 'risk control', data: {} },
    { code: 0, data: { v_voucher: 'challenge', list: [] } },
    { code: 0, __http: 412, data: { list: [] } },
    { code: 0, __http: 403, data: { list: [] } },
  ]) {
    assert.throws(
      () => normalizeWatchLaterPayload(payload),
      (error) => {
        assert.equal(error.code, 'BILIBILI_RISK_CONTROL')
        assert.equal(error.retryable, true)
        return /risk control/i.test(error.message)
      },
    )
  }
  assert.throws(
    () => normalizeWatchLaterPayload({ code: 0, data: { list: [{}] } }),
    /malformed/i,
  )
})

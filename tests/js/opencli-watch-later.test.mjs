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

test('rejects login failures and malformed rows', () => {
  assert.throws(
    () => normalizeWatchLaterPayload({ code: -101, message: 'not logged in' }),
    /login/i,
  )
  assert.throws(
    () => normalizeWatchLaterPayload({ code: 0, data: { list: [{}] } }),
    /malformed/i,
  )
})

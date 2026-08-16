import { AuthRequiredError, CliError, CommandExecutionError, EXIT_CODES } from '@jackwener/opencli/errors'
import { cli, Strategy } from '@jackwener/opencli/registry'

import { normalizeWatchLaterPayload } from './lib/normalize-watch-later.mjs'

cli({
  site: 'video-subtitle-watch-later',
  name: 'list',
  access: 'read',
  description: 'Read the current Bilibili Watch Later list without modifying it',
  domain: 'www.bilibili.com',
  strategy: Strategy.COOKIE,
  browser: true,
  args: [
    { name: 'limit', type: 'int', default: 100, help: 'Number of entries (max 100)' },
  ],
  columns: ['bvid', 'page', 'title', 'url', 'position', 'addedAt'],
  func: async (page, kwargs) => {
    const payload = await page.evaluate(`
      async () => {
        const response = await fetch('https://api.bilibili.com/x/v2/history/toview', {
          credentials: 'include',
          headers: { Accept: 'application/json' },
        });
        const text = await response.text();
        try {
          const payload = JSON.parse(text);
          if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
            return { ...payload, __http: response.status };
          }
          return payload;
        } catch {
          return {
            code: -1,
            __http: response.status,
            message: 'Non-JSON response (HTTP ' + response.status + '): ' + text.slice(0, 160),
          };
        }
      }
    `)
    try {
      return normalizeWatchLaterPayload(payload, kwargs.limit)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (error?.authRequired === true) {
        throw new AuthRequiredError('bilibili.com', message)
      }
      if (error?.retryable === true) {
        throw new CliError(
          error.code ?? 'BILIBILI_TEMPORARY_FAILURE',
          message,
          'Wait a few minutes and retry without increasing scan frequency.',
          EXIT_CODES.TEMPFAIL,
        )
      }
      throw new CommandExecutionError(message)
    }
  },
})

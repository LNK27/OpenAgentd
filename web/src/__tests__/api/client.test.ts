import { afterEach, describe, expect, it, mock } from 'bun:test'
import { postTeamChat } from '@/api/client'
import { CODING_WORKSPACE_BUSY_MESSAGE } from '@/utils/workspace'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('postTeamChat', () => {
  it('shows a specific coding workspace concurrency error on 409', async () => {
    globalThis.fetch = mock(() => Promise.resolve(new Response(JSON.stringify({ detail: 'busy' }), { status: 409 }))) as typeof fetch

    await expect(postTeamChat('hello', null, false, undefined, 'coding', '/repo/app')).rejects.toThrow(
      CODING_WORKSPACE_BUSY_MESSAGE,
    )
  })

  it('uses backend detail for non-coding 409 errors', async () => {
    globalThis.fetch = mock(() => Promise.resolve(new Response(JSON.stringify({ detail: 'conflict' }), { status: 409 }))) as typeof fetch

    await expect(postTeamChat('hello')).rejects.toThrow('conflict')
  })

  it('sends coding mode and workspace with the chat form', async () => {
    let body: BodyInit | null | undefined
    globalThis.fetch = mock((_url, init) => {
      body = (init as RequestInit | undefined)?.body
      return Promise.resolve(new Response(JSON.stringify({ status: 'accepted', session_id: 'sid' })))
    }) as typeof fetch

    await postTeamChat('hello', null, false, undefined, 'coding', '/repo/app')

    expect(body).toBeInstanceOf(FormData)
    const form = body as FormData
    expect(form.get('mode')).toBe('coding')
    expect(form.get('workspace')).toBe('/repo/app')
  })
})

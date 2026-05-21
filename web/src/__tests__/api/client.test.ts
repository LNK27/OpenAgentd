import { afterEach, describe, expect, it, mock } from 'bun:test'
import { cancelQueuedTeamMessage, postTeamChat } from '@/api/client'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('postTeamChat', () => {
  it('uses backend detail for non-coding 409 errors', async () => {
    globalThis.fetch = mock(() => Promise.resolve(new Response(JSON.stringify({ detail: 'conflict' }), { status: 409 }))) as typeof fetch

    await expect(postTeamChat('hello')).rejects.toThrow('conflict')
  })

  it('uses backend detail for coding 409 errors', async () => {
    globalThis.fetch = mock(() => Promise.resolve(new Response(JSON.stringify({ detail: 'Session belongs to a different coding workspace' }), { status: 409 }))) as typeof fetch

    await expect(postTeamChat('hello', null, false, undefined, 'coding', '/repo/app')).rejects.toThrow(
      'Session belongs to a different coding workspace',
    )
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

  it('deletes queued messages by session and message id', async () => {
    let url: string | URL | Request | undefined
    let method: string | undefined
    globalThis.fetch = mock((input, init) => {
      url = input as string | URL | Request
      method = (init as RequestInit | undefined)?.method
      return Promise.resolve(new Response(null, { status: 204 }))
    }) as typeof fetch

    await cancelQueuedTeamMessage('sid', 'mid')

    expect(String(url)).toBe('/api/team/sessions/sid/queued-messages/mid')
    expect(method).toBe('DELETE')
  })
})

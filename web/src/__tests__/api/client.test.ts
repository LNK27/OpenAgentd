import { afterEach, describe, expect, it, mock } from 'bun:test'
import { cancelQueuedTeamMessage, postTeamChat, resolveTeamSession, updateTeamSessionTitle } from '@/api/client'

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

  it('omits model settings when they are undefined', async () => {
    let body: BodyInit | null | undefined
    globalThis.fetch = mock((_url, init) => {
      body = (init as RequestInit | undefined)?.body
      return Promise.resolve(new Response(JSON.stringify({ status: 'accepted', session_id: 'sid' })))
    }) as typeof fetch

    await postTeamChat('hello')

    const form = body as FormData
    expect(form.has('model')).toBe(false)
    expect(form.has('thinking_level')).toBe(false)
  })

  it('sends empty form fields for explicit model setting resets', async () => {
    let body: BodyInit | null | undefined
    globalThis.fetch = mock((_url, init) => {
      body = (init as RequestInit | undefined)?.body
      return Promise.resolve(new Response(JSON.stringify({ status: 'accepted', session_id: 'sid' })))
    }) as typeof fetch

    await postTeamChat('hello', 'sid', false, undefined, 'normal', null, null, null)

    const form = body as FormData
    expect(form.has('model')).toBe(true)
    expect(form.get('model')).toBe('')
    expect(form.has('thinking_level')).toBe(true)
    expect(form.get('thinking_level')).toBe('')
  })

  it('sends selected model settings exactly when provided', async () => {
    let body: BodyInit | null | undefined
    globalThis.fetch = mock((_url, init) => {
      body = (init as RequestInit | undefined)?.body
      return Promise.resolve(new Response(JSON.stringify({ status: 'accepted', session_id: 'sid' })))
    }) as typeof fetch

    await postTeamChat('hello', 'sid', false, undefined, 'normal', null, 'openai:gpt-5.5', 'high')

    const form = body as FormData
    expect(form.get('model')).toBe('openai:gpt-5.5')
    expect(form.get('thinking_level')).toBe('high')
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

  it('treats missing queued messages as already cancelled', async () => {
    globalThis.fetch = mock(() => Promise.resolve(new Response(JSON.stringify({ detail: 'not found' }), { status: 404 }))) as typeof fetch

    await expect(cancelQueuedTeamMessage('sid', 'mid')).resolves.toBeUndefined()
  })
})

describe('resolveTeamSession', () => {
  it('posts mode, workspace, and model settings as JSON', async () => {
    let url = ''
    let init: RequestInit | undefined
    globalThis.fetch = mock((input, requestInit) => {
      url = String(input)
      init = requestInit as RequestInit | undefined
      return Promise.resolve(new Response(JSON.stringify({
        id: 'sid',
        title: null,
        agent_name: null,
        mode: 'coding',
        workspace: '/repo/app',
        model: 'openai:gpt-5.5',
        thinking_level: 'high',
        created_at: null,
        updated_at: null,
        created: true,
      })))
    }) as typeof fetch

    const result = await resolveTeamSession({
      mode: 'coding',
      workspace: '/repo/app',
      model: 'openai:gpt-5.5',
      thinkingLevel: 'high',
      create: true,
    })

    expect(url).toBe('/api/team/sessions/resolve')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init?.body as string)).toEqual({
      mode: 'coding',
      workspace: '/repo/app',
      model: 'openai:gpt-5.5',
      thinking_level: 'high',
      create: true,
    })
    expect(result.created).toBe(true)
    expect(result.id).toBe('sid')
  })

  it('throws when backend rejects resolve request', async () => {
    globalThis.fetch = mock(() => Promise.resolve(new Response('bad', { status: 422 }))) as typeof fetch

    await expect(resolveTeamSession({ mode: 'coding' })).rejects.toThrow('resolveTeamSession failed: 422')
  })
})

describe('updateTeamSessionTitle', () => {
  it('patches only the title as JSON and returns the updated session', async () => {
    let url = ''
    let init: RequestInit | undefined
    globalThis.fetch = mock((input, requestInit) => {
      url = String(input)
      init = requestInit as RequestInit | undefined
      return Promise.resolve(new Response(JSON.stringify({
        id: 'sid',
        title: 'Renamed session',
        agent_name: 'lead',
        created_at: null,
        updated_at: null,
      })))
    }) as typeof fetch

    const result = await updateTeamSessionTitle('sid', 'Renamed session')

    expect(url).toBe('/api/team/sessions/sid')
    expect(init?.method).toBe('PATCH')
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init?.body as string)).toEqual({ title: 'Renamed session' })
    expect(result.title).toBe('Renamed session')
  })

  it('throws when the backend rejects the title update', async () => {
    globalThis.fetch = mock(() => Promise.resolve(new Response('bad', { status: 422 }))) as typeof fetch

    await expect(updateTeamSessionTitle('sid', '')).rejects.toThrow('updateTeamSessionTitle failed: 422')
  })
})

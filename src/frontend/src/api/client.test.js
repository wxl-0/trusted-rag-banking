import assert from 'node:assert/strict'
import test from 'node:test'

import {
  askQuestionStream,
  createConversation,
  fetchConversation,
  toDisplayMessages,
} from './client.js'

test('askQuestionStream parses SSE events split across network chunks', async () => {
  const encoder = new TextEncoder()
  const chunks = [
    'event: progress\ndata: {"stage":"analy',
    'zing","message":"正在分析问题"}\n\n',
    'event: answer\ndata: {"answer":"完成","evidence":[],',
    '"refuse_reason":null,"latency_ms":10}\n\n',
  ]
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/ask/stream')
    assert.equal(options.method, 'POST')
    assert.equal(options.headers.Authorization, 'Bearer access-token')
    assert.deepEqual(JSON.parse(options.body), {
      question: '问题',
      filters: null,
      conversation_id: 'conversation-1',
      request_id: 'request-1',
    })
    return new Response(new ReadableStream({
      start(controller) {
        chunks.forEach(chunk => controller.enqueue(encoder.encode(chunk)))
        controller.close()
      },
    }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
  }
  const events = []

  try {
    const answer = await askQuestionStream({
      question: '问题',
      conversationId: 'conversation-1',
      requestId: 'request-1',
      onEvent: (event, data) => events.push([event, data]),
      accessToken: 'access-token',
    })
    assert.deepEqual(events, [[
      'progress', { stage: 'analyzing', message: '正在分析问题' },
    ]])
    assert.deepEqual(answer, {
      answer: '完成', evidence: [], refuse_reason: null, latency_ms: 10,
    })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('conversation client creates and restores displayable messages', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  const conversation = {
    id: 'conversation-1',
    messages: [
      {
        id: 'message-1',
        request_id: 'request-1',
        role: 'user',
        content: '已保存的问题',
        evidence: [],
        refuse_reason: null,
        latency_ms: null,
      },
      {
        id: 'message-2',
        request_id: 'request-1',
        role: 'assistant',
        content: '已保存的回答',
        evidence: [{ source_title: '监管制度', section: '', text: '原文', source_url: '' }],
        refuse_reason: null,
        latency_ms: 30,
      },
    ],
  }
  globalThis.fetch = async (url, options = {}) => {
    calls.push([url, options])
    return new Response(JSON.stringify(
      url === '/api/conversations' ? { ...conversation, messages: [] } : conversation,
    ), { status: url === '/api/conversations' ? 201 : 200 })
  }

  try {
    const created = await createConversation('access-token')
    const restored = await fetchConversation(created.id, 'access-token')

    assert.equal(calls[0][0], '/api/conversations')
    assert.equal(calls[0][1].method, 'POST')
    assert.equal(calls[0][1].headers.Authorization, 'Bearer access-token')
    assert.equal(calls[1][0], '/api/conversations/conversation-1')
    assert.equal(calls[1][1].headers.Authorization, 'Bearer access-token')
    assert.deepEqual(toDisplayMessages(restored.messages), [
      { id: 'message-1', role: 'user', content: '已保存的问题' },
      {
        id: 'message-2',
        role: 'assistant',
        content: {
          answer: '已保存的回答',
          evidence: conversation.messages[1].evidence,
          refuse_reason: null,
          latency_ms: 30,
        },
      },
    ])
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('fetchConversation returns null for an unavailable active conversation', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { code: 'CONVERSATION_NOT_FOUND', message: '对话不存在' },
  }), { status: 404 })

  try {
    assert.equal(await fetchConversation('missing', 'access-token'), null)
  } finally {
    globalThis.fetch = originalFetch
  }
})

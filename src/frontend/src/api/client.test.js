import assert from 'node:assert/strict'
import test from 'node:test'

import {
  askQuestionStream,
  createConversation,
  deleteConversation,
  fetchConversation,
  fetchKnowledgeDocument,
  fetchKnowledgeSummary,
  listConversations,
  listKnowledgeDocuments,
  renameConversation,
  toDisplayMessages,
  uploadKnowledgeDocument,
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

test('history client lists renames and deletes conversations', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push([url, options])
    if (options.method === 'DELETE') return new Response(null, { status: 204 })
    return new Response(JSON.stringify(
      options.method === 'PATCH'
        ? { id: 'c1', title: '新标题' }
        : { items: [{ id: 'c1', title: '旧标题' }], next_cursor: null },
    ), { status: 200 })
  }

  try {
    await listConversations('贷款', null, 'token')
    await renameConversation('c1', '新标题', 'token')
    await deleteConversation('c1', 'token')
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(calls[0][0], '/api/conversations?search=%E8%B4%B7%E6%AC%BE')
  assert.equal(calls[0][1].headers.Authorization, 'Bearer token')
  assert.deepEqual(JSON.parse(calls[1][1].body), { title: '新标题' })
  assert.equal(calls[1][1].method, 'PATCH')
  assert.equal(calls[2][1].method, 'DELETE')
})

test('knowledge document client reads summary filtered list and detail', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push([url, options])
    return new Response(JSON.stringify(
      url.endsWith('/summary')
        ? { succeeded: 1, in_progress: 2, failed: 3, updated_at: null }
        : url.includes('document-1')
          ? { id: 'document-1', original_filename: '监管办法.pdf' }
          : { items: [], next_cursor: null },
    ), { status: 200 })
  }

  try {
    await fetchKnowledgeSummary('access-token')
    await listKnowledgeDocuments({
      search: '资本',
      status: 'in_progress',
      page: 2,
      limit: 10,
      accessToken: 'access-token',
    })
    await fetchKnowledgeDocument('document-1', 'access-token')
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(calls[0][0], '/api/knowledge-documents/summary')
  assert.equal(calls[0][1].headers.Authorization, 'Bearer access-token')
  assert.equal(
    calls[1][0],
    '/api/knowledge-documents?search=%E8%B5%84%E6%9C%AC&status=in_progress&page=2&limit=10',
  )
  assert.equal(calls[2][0], '/api/knowledge-documents/document-1')
  assert.equal(calls[2][1].headers.Authorization, 'Bearer access-token')
})

test('knowledge document client uploads one file as multipart data', async () => {
  const originalFetch = globalThis.fetch
  let request
  globalThis.fetch = async (url, options) => {
    request = [url, options]
    return new Response(JSON.stringify({
      document_id: 'document-1',
      version_id: 'version-1',
      task_id: 'task-1',
      status: 'in_progress',
    }), { status: 202 })
  }
  const file = new File(['document'], '监管办法.pdf', { type: 'application/pdf' })

  try {
    const result = await uploadKnowledgeDocument(file, 'access-token')
    assert.equal(result.status, 'in_progress')
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(request[0], '/api/knowledge-documents')
  assert.equal(request[1].method, 'POST')
  assert.equal(request[1].headers.Authorization, 'Bearer access-token')
  assert.equal(request[1].headers['Content-Type'], undefined)
  assert.equal(request[1].body.get('file'), file)
})

test('knowledge upload client exposes the safe server validation message', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { code: 'UPLOAD_INVALID_CONTENT', message: '文件内容与扩展名不匹配或文件已损坏' },
  }), { status: 422 })

  try {
    await assert.rejects(
      uploadKnowledgeDocument(new File(['bad'], '伪装文件.pdf'), 'access-token'),
      /文件内容与扩展名不匹配或文件已损坏/,
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

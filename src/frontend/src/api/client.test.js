import assert from 'node:assert/strict'
import test from 'node:test'

import { askQuestionStream, buildHistory } from './client.js'

test('buildHistory includes only completed messages before the current question', () => {
  const messages = [
    { role: 'user', content: '上一轮问题' },
    {
      role: 'assistant',
      content: { answer: '上一轮回答', evidence: [], refuse_reason: null },
    },
    {
      role: 'assistant',
      content: { processing: true, message: '正在处理' },
    },
  ]

  assert.deepEqual(buildHistory(messages), [
    { role: 'user', content: '上一轮问题' },
    { role: 'assistant', content: '上一轮回答' },
  ])
})

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
    return new Response(new ReadableStream({
      start(controller) {
        chunks.forEach(chunk => controller.enqueue(encoder.encode(chunk)))
        controller.close()
      },
    }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
  }
  const events = []

  try {
    const answer = await askQuestionStream(
      '问题', null, [], (event, data) => events.push([event, data]), 'access-token',
    )
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

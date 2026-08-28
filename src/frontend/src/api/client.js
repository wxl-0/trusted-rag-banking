function requestHeaders(accessToken) {
  return {
    'Content-Type': 'application/json',
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  }
}

async function responseError(response, fallback) {
  const payload = await response.json().catch(() => ({}))
  const detail = payload.detail
  return detail?.message || (typeof detail === 'string' ? detail : fallback)
}

export async function fetchIdentity(accessToken) {
  const response = await fetch('/api/auth/me', {
    headers: requestHeaders(accessToken),
  })
  if (!response.ok) throw new Error(await responseError(response, '身份读取失败'))
  return response.json()
}

export async function createConversation(accessToken) {
  const response = await fetch('/api/conversations', {
    method: 'POST',
    headers: requestHeaders(accessToken),
  })
  if (!response.ok) {
    throw new Error(await responseError(response, '创建对话失败'))
  }
  return response.json()
}

export async function fetchConversation(conversationId, accessToken) {
  const response = await fetch(`/api/conversations/${conversationId}`, {
    headers: requestHeaders(accessToken),
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(await responseError(response, '读取对话失败'))
  }
  return response.json()
}

export function toDisplayMessages(messages) {
  return messages.map(message => (
    message.role === 'user'
      ? { id: message.id, role: 'user', content: message.content }
      : {
          id: message.id,
          role: 'assistant',
          content: {
            answer: message.content,
            evidence: message.evidence,
            refuse_reason: message.refuse_reason,
            latency_ms: message.latency_ms,
          },
        }
  ))
}

export async function askQuestion(
  question, filters = null, history = null, accessToken = null,
) {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: requestHeaders(accessToken),
    body: JSON.stringify({ question, filters, history }),
  })
  if (!response.ok) {
    throw new Error(await responseError(response, '请求失败'))
  }
  return response.json()
}

function parseEvent(block) {
  let event = 'message'
  const data = []
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  return { event, data: JSON.parse(data.join('\n')) }
}

export async function askQuestionStream({
  question,
  conversationId,
  requestId,
  filters = null,
  onEvent = () => {},
  accessToken = null,
}) {
  const response = await fetch('/api/ask/stream', {
    method: 'POST',
    headers: requestHeaders(accessToken),
    body: JSON.stringify({
      question,
      filters,
      conversation_id: conversationId,
      request_id: requestId,
    }),
  })
  if (!response.ok) {
    throw new Error(await responseError(response, '请求失败'))
  }
  if (!response.body) throw new Error('浏览器不支持流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer = null

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    let separator = buffer.match(/\r?\n\r?\n/)
    while (separator) {
      const block = buffer.slice(0, separator.index)
      buffer = buffer.slice(separator.index + separator[0].length)
      if (block.trim()) {
        const parsed = parseEvent(block)
        if (parsed.event === 'answer') answer = parsed.data
        else if (parsed.event === 'error') {
          throw new Error(parsed.data.message || '处理失败')
        } else {
          onEvent(parsed.event, parsed.data)
        }
      }
      separator = buffer.match(/\r?\n\r?\n/)
    }
    if (done) break
  }

  if (!answer) throw new Error('回答流意外中断')
  return answer
}

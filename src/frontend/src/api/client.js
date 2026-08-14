export function buildHistory(messages) {
  return messages
    .filter(message => (
      message.role === 'user'
      || (message.role === 'assistant' && message.content.answer)
    ))
    .map(message => ({
      role: message.role,
      content: message.role === 'user' ? message.content : message.content.answer,
    }))
}

export async function askQuestion(question, filters = null, history = null) {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, filters, history }),
  })
  if (!response.ok) {
    const err = await response.json()
    throw new Error(err.detail || '请求失败')
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

export async function askQuestionStream(
  question,
  filters = null,
  history = null,
  onEvent = () => {},
) {
  const response = await fetch('/api/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, filters, history }),
  })
  if (!response.ok) {
    const err = await response.json()
    throw new Error(err.detail || '请求失败')
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

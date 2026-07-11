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

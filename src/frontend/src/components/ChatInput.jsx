import { useState } from 'react'

export default function ChatInput({ onSend, loading }) {
  const [value, setValue] = useState('')
  const submit = event => {
    event?.preventDefault()
    if (!value.trim() || loading) return
    onSend(value.trim())
    setValue('')
  }

  const updateValue = event => {
    setValue(event.target.value)
    event.target.style.height = 'auto'
    event.target.style.height = `${Math.min(event.target.scrollHeight, 110)}px`
  }

  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={submit}>
        <textarea
          rows="1"
          value={value}
          onChange={updateValue}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey) submit(event)
          }}
          placeholder="输入监管制度问题"
          disabled={loading}
        />
        <button
          type="submit"
          aria-label="发送问题"
          disabled={loading || !value.trim()}
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M10 15V5M6 9l4-4 4 4" />
          </svg>
        </button>
      </form>
      <p>回答由企业知识库生成，请结合原文证据核验重要结论。</p>
    </div>
  )
}

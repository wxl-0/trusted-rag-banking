import { useState } from 'react'

export default function ChatInput({ onSend, loading }) {
  const [value, setValue] = useState('')
  const submit = () => {
    if (!value.trim() || loading) return
    onSend(value.trim())
    setValue('')
  }
  return (
    <div className="chat-input-area">
      <div className="chat-input-wrapper">
        <input
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder="输入监管制度问题，按 Enter 发送..."
          disabled={loading}
        />
        <button
          className="send-btn"
          onClick={submit}
          disabled={loading || !value.trim()}
        >
          {loading ? <span className="loading-dots"><span>.</span><span>.</span><span>.</span></span> : '发送'}
        </button>
      </div>
    </div>
  )
}

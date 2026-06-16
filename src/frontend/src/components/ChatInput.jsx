import { useState } from 'react'

export default function ChatInput({ onSend, loading }) {
  const [value, setValue] = useState('')
  const submit = () => {
    if (!value.trim() || loading) return
    onSend(value.trim())
    setValue('')
  }
  return (
    <div style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid #eee' }}>
      <input
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && submit()}
        placeholder="输入监管制度问题，按 Enter 发送..."
        style={{ flex: 1, padding: '8px 12px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 14 }}
        disabled={loading}
      />
      <button
        onClick={submit}
        disabled={loading || !value.trim()}
        style={{ padding: '8px 20px', borderRadius: 6, background: '#1890ff', color: '#fff', border: 'none', cursor: 'pointer', opacity: (loading || !value.trim()) ? 0.6 : 1 }}
      >
        {loading ? '...' : '发送'}
      </button>
    </div>
  )
}

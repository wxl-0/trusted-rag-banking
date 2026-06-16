import { useState } from 'react'
import MessageList from './components/MessageList'
import ChatInput from './components/ChatInput'
import { askQuestion } from './api/client'

export default function App() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)

  const handleSend = async (question) => {
    setMessages(prev => [...prev, { role: 'user', content: question }])
    setLoading(true)
    try {
      const result = await askQuestion(question)
      setMessages(prev => [...prev, { role: 'assistant', content: result }])
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: { answer: '', confidence: 'low', evidence: [], refuse_reason: err.message }
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', maxWidth: 800, margin: '0 auto', fontFamily: 'sans-serif' }}>
      <div style={{ padding: 16, borderBottom: '1px solid #eee', fontWeight: 'bold', fontSize: 18 }}>
        银行业监管制度问答系统
      </div>
      <MessageList messages={messages} />
      <ChatInput onSend={handleSend} loading={loading} />
    </div>
  )
}

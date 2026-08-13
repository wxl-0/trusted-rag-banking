import { useState } from 'react'
import MessageList from './components/MessageList'
import ChatInput from './components/ChatInput'
import { askQuestion } from './api/client'

export default function App() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)

  const handleSend = async (question) => {
    const newMessages = [...messages, { role: 'user', content: question }]
    setMessages(newMessages)
    setLoading(true)

    const history = newMessages
      .filter(m => m.role === 'user' || (m.role === 'assistant' && m.content.answer))
      .map(m => ({
        role: m.role,
        content: m.role === 'user' ? m.content : m.content.answer,
      }))

    try {
      const result = await askQuestion(question, null, history)
      setMessages(prev => [...prev, { role: 'assistant', content: result }])
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: { answer: '', evidence: [], refuse_reason: err.message }
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <img src="/logo.png" alt="南京银行" />
        <span className="header-title">监管制度智能问答</span>
      </header>
      <MessageList messages={messages} />
      <ChatInput onSend={handleSend} loading={loading} />
    </div>
  )
}

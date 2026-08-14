import { useState } from 'react'
import MessageList from './components/MessageList'
import ChatInput from './components/ChatInput'
import { askQuestionStream, buildHistory } from './api/client'

export default function App() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)

  const handleSend = async (question) => {
    const newMessages = [...messages, { role: 'user', content: question }]
    const requestId = `${Date.now()}-${Math.random()}`
    setMessages([...newMessages, {
      role: 'assistant',
      requestId,
      content: {
        processing: true,
        stage: 'connecting',
        message: '正在提交问题',
        startedAt: Date.now(),
      },
    }])
    setLoading(true)

    const history = buildHistory(messages)

    try {
      const result = await askQuestionStream(
        question,
        null,
        history,
        (event, data) => {
          if (event !== 'progress') return
          setMessages(prev => prev.map(message => (
            message.requestId === requestId
              ? { ...message, content: { ...message.content, ...data } }
              : message
          )))
        },
      )
      setMessages(prev => prev.map(message => (
        message.requestId === requestId
          ? { role: 'assistant', content: result }
          : message
      )))
    } catch (err) {
      setMessages(prev => prev.map(message => (
        message.requestId === requestId
          ? {
              role: 'assistant',
              content: { answer: '', evidence: [], refuse_reason: err.message },
            }
          : message
      )))
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

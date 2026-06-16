import AnswerCard from './AnswerCard'

export default function MessageList({ messages }) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
      {messages.length === 0 && (
        <div style={{ textAlign: 'center', color: '#aaa', marginTop: 60 }}>
          输入银行业监管制度相关问题开始问答
        </div>
      )}
      {messages.map((msg, i) => <AnswerCard key={i} message={msg} />)}
    </div>
  )
}

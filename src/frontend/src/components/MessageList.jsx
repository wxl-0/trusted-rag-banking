import AnswerCard from './AnswerCard'

export default function MessageList({ messages }) {
  return (
    <div className="message-list">
      {messages.length === 0 && (
        <div className="empty-state">
          <img className="intro-logo" src="/logo-vertical.png" alt="南京银行" />
          <h2>银行业监管制度智能问答</h2>
        </div>
      )}
      {messages.map((msg, i) => <AnswerCard key={i} message={msg} />)}
    </div>
  )
}

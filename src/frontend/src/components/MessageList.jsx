import AnswerCard from './AnswerCard'
import EmptyState from './EmptyState'

export default function MessageList({ messages }) {
  return (
    <div className="message-list">
      {messages.length === 0 && (
        <EmptyState />
      )}
      {messages.map((msg, i) => <AnswerCard key={i} message={msg} />)}
    </div>
  )
}

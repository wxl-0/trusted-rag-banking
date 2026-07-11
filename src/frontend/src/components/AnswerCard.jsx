import EvidencePanel from './EvidencePanel'

export default function AnswerCard({ message }) {
  if (message.role === 'user') {
    return (
      <div className="msg-user">
        <div className="bubble">{message.content}</div>
      </div>
    )
  }
  const { answer, evidence, refuse_reason } = message.content
  return (
    <div className="msg-assistant">
      <div className="answer-card">
        {refuse_reason ? (
          <div className="refuse">{refuse_reason}</div>
        ) : (
          <>
            <div className="answer-text">{answer}</div>
            <EvidencePanel evidence={evidence} />
          </>
        )}
      </div>
    </div>
  )
}

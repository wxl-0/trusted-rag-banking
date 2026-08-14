import EvidencePanel from './EvidencePanel'
import ProcessingCard from './ProcessingCard'

function formatLatency(milliseconds) {
  if (milliseconds < 60000) return `${(milliseconds / 1000).toFixed(1)} 秒`
  const minutes = Math.floor(milliseconds / 60000)
  const seconds = ((milliseconds % 60000) / 1000).toFixed(1)
  return `${minutes} 分 ${seconds} 秒`
}

export default function AnswerCard({ message }) {
  if (message.role === 'user') {
    return (
      <div className="msg-user">
        <div className="bubble">{message.content}</div>
      </div>
    )
  }
  if (message.content.processing) {
    return (
      <div className="msg-assistant">
        <ProcessingCard content={message.content} />
      </div>
    )
  }
  const { answer, evidence, refuse_reason, latency_ms } = message.content
  return (
    <div className="msg-assistant">
      <div className="answer-card">
        {refuse_reason ? (
          <div className="refuse">{refuse_reason}</div>
        ) : (
          <>
            <div className="answer-text">{answer}</div>
            <EvidencePanel evidence={evidence} />
            {latency_ms != null && (
              <div className="answer-latency">
                处理完成 · {formatLatency(latency_ms)}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

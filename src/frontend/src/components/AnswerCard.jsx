import EvidencePanel from './EvidencePanel'

const confidenceColor = { high: '#52c41a', medium: '#faad14', low: '#ff4d4f' }
const confidenceLabel = { high: '高', medium: '中', low: '低' }

export default function AnswerCard({ message }) {
  if (message.role === 'user') {
    return (
      <div style={{ textAlign: 'right', margin: '8px 0' }}>
        <span style={{ background: '#1890ff', color: '#fff', borderRadius: 12, padding: '6px 14px', display: 'inline-block', maxWidth: '70%' }}>
          {message.content}
        </span>
      </div>
    )
  }
  const { answer, confidence, evidence, refuse_reason } = message.content
  return (
    <div style={{ margin: '8px 0', padding: 12, background: '#f5f5f5', borderRadius: 8, maxWidth: '80%' }}>
      {refuse_reason ? (
        <div style={{ color: '#ff4d4f' }}>⚠️ {refuse_reason}</div>
      ) : (
        <>
          <div style={{ marginBottom: 6 }}>
            <span style={{ background: confidenceColor[confidence] || '#ccc', color: '#fff', borderRadius: 4, padding: '1px 6px', fontSize: 11, marginRight: 6 }}>
              置信度·{confidenceLabel[confidence] || confidence}
            </span>
          </div>
          <div style={{ lineHeight: 1.7 }}>{answer}</div>
          <EvidencePanel evidence={evidence} />
        </>
      )}
    </div>
  )
}

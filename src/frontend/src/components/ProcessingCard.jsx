import { useEffect, useState } from 'react'

const stages = [
  ['analyzing', '分析问题'],
  ['retrieving', '检索资料'],
  ['organizing', '整理证据'],
  ['generating', '生成答案'],
]

function formatElapsed(seconds) {
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分钟`
}

export default function ProcessingCard({ content }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const update = () => {
      setElapsed(Math.max(0, Math.floor((Date.now() - content.startedAt) / 1000)))
    }
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [content.startedAt])

  const activeIndex = stages.findIndex(([id]) => id === content.stage)

  return (
    <div className="processing-card" role="status" aria-live="polite">
      <div className="processing-head">
        <span className="processing-pulse" aria-hidden="true" />
        <span className="processing-message">{content.message}</span>
        <span className="processing-time">已用时 {formatElapsed(elapsed)}</span>
      </div>
      <div className="processing-track" aria-label="回答处理进度">
        {stages.map(([id, label], index) => {
          const state = index < activeIndex ? 'done' : index === activeIndex ? 'active' : ''
          return (
            <div className={`processing-step ${state}`} key={id}>
              <span className="step-dot" aria-hidden="true">{state === 'done' ? '✓' : ''}</span>
              <span>{label}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

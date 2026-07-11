import { useState } from 'react'

export default function EvidencePanel({ evidence }) {
  const [open, setOpen] = useState(false)
  if (!evidence || evidence.length === 0) return null
  return (
    <div className="evidence-section">
      <button className="evidence-toggle" onClick={() => setOpen(!open)}>
        {open ? '▲' : '▼'} 证据来源 ({evidence.length})
      </button>
      {open && (
        <div className="evidence-list">
          {evidence.map((e, i) => (
            <div key={i} className="evidence-item">
              <span className="ev-title">《{e.source_title}》</span>
              {e.section && <span className="ev-section"> · {e.section}</span>}
              <div className="ev-text">"{e.text}"</div>
              {e.source_url && (
                <a href={e.source_url} target="_blank" rel="noreferrer" className="ev-link">查看原文</a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

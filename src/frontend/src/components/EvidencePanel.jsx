import { useState } from 'react'

export default function EvidencePanel({ evidence }) {
  const [open, setOpen] = useState(false)
  if (!evidence || evidence.length === 0) return null
  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{ cursor: 'pointer', background: 'none', border: '1px solid #ccc', borderRadius: 4, padding: '2px 8px', fontSize: 12 }}
      >
        {open ? '▲' : '▼'} 证据来源 ({evidence.length})
      </button>
      {open && (
        <div style={{ marginTop: 6, paddingLeft: 12, borderLeft: '3px solid #1890ff' }}>
          {evidence.map((e, i) => (
            <div key={i} style={{ marginBottom: 10, fontSize: 13 }}>
              <div><strong>《{e.source_title}》</strong>{e.section ? ` · ${e.section}` : ''}</div>
              <div style={{ color: '#555', margin: '2px 0' }}>"{e.text}"</div>
              {e.source_url && (
                <a href={e.source_url} target="_blank" rel="noreferrer" style={{ color: '#1890ff', fontSize: 12 }}>查看原文</a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

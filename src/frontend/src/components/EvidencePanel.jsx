import { useState } from 'react'

export default function EvidencePanel({ evidence }) {
  const [open, setOpen] = useState(false)
  if (!evidence || evidence.length === 0) return null
  return (
    <>
      <button
        className={`evidence-button ${open ? 'is-open' : ''}`}
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M4 3.5h9l3 3V16.5H4v-13Z" />
          <path d="M13 3.5v3h3M7 10h6M7 13h4" />
        </svg>
        查看 {evidence.length} 条原文证据
        <svg className="evidence-chevron" viewBox="0 0 20 20" aria-hidden="true">
          <path d="m6 8 4 4 4-4" />
        </svg>
      </button>
      {open && (
        <div className="evidence-list">
          {evidence.map((e, i) => (
            <blockquote key={i}>
              <strong>《{e.source_title}》{e.section}</strong>
              <p>{e.text}</p>
              {e.source_url && (
                <a href={e.source_url} target="_blank" rel="noreferrer">查看原文</a>
              )}
            </blockquote>
          ))}
        </div>
      )}
    </>
  )
}

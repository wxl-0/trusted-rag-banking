const capabilities = [
  {
    id: 'regulation',
    title: '制度检索',
    description: '定位条款、名单与监管要求',
  },
  {
    id: 'data',
    title: '数据取数',
    description: '查询 Excel / PDF 统计指标',
  },
  {
    id: 'calculation',
    title: '对比计算',
    description: '完成跨期变化与多指标比较',
  },
  {
    id: 'evidence',
    title: '证据回答',
    description: '每个结论均可追溯原文',
  },
]

function CapabilityIcon({ type }) {
  if (type === 'regulation') {
    return (
      <svg viewBox="0 0 48 48" aria-hidden="true">
        <path d="M12 7h17l7 7v13" />
        <path d="M29 7v8h7M18 21h11M18 27h7" />
        <circle cx="33" cy="34" r="7" />
        <path d="m38 39 5 5" />
      </svg>
    )
  }
  if (type === 'data') {
    return (
      <svg viewBox="0 0 48 48" aria-hidden="true">
        <rect x="7" y="9" width="34" height="30" rx="3" />
        <path d="M7 18h34M19 18v21M30 18v21M7 28h34" />
        <path d="M33 33h5" />
      </svg>
    )
  }
  if (type === 'calculation') {
    return (
      <svg viewBox="0 0 48 48" aria-hidden="true">
        <path d="M7 14h22M7 14l6-6M7 14l6 6M28 34H7M28 34l-6-6M28 34l-6 6" />
        <rect x="30" y="19" width="12" height="22" rx="2" />
        <path d="M33 24h6M34 30h1M38 30h1M34 35h1M38 35h1" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path d="M24 5 39 11v11c0 10-6 17-15 21C15 39 9 32 9 22V11l15-6Z" />
      <path d="m17 24 5 5 10-11" />
    </svg>
  )
}

export default function EmptyState() {
  return (
    <section className="empty-state" aria-labelledby="empty-state-title">
      <div className="knowledge-badge">
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M10 2.5 16 5v4.4c0 4-2.4 6.8-6 8.1-3.6-1.3-6-4.1-6-8.1V5l6-2.5Z" />
          <path d="m7 9.8 2 2 4-4" />
        </svg>
        可信监管知识库
      </div>
      <h1 id="empty-state-title">有依据地查制度、找数据、做计算</h1>
      <div className="capability-grid">
        {capabilities.map(capability => (
          <article className="capability-card" key={capability.id}>
            <div className="capability-icon">
              <CapabilityIcon type={capability.id} />
            </div>
            <h2>{capability.title}</h2>
            <p>{capability.description}</p>
          </article>
        ))}
      </div>
    </section>
  )
}

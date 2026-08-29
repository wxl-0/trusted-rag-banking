const STATUS_LABELS = {
  succeeded: '成功',
  in_progress: '进行中',
  failed: '失败',
}

const TASK_STATE_LABELS = {
  queued: '等待处理',
  parsing: '正在解析',
  indexing: '正在构建索引',
  succeeded: '成功',
  failed: '失败',
}


function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function formatTime(value) {
  if (!value) return '暂无更新'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function DetailItem({ label, children }) {
  return (
    <div className="detail-item">
      <span>{label}</span>
      <strong>{children}</strong>
    </div>
  )
}


export default function KnowledgeBasePage({
  summary,
  documents,
  detail,
  loading,
  error,
  search,
  status,
  nextCursor,
  onSearch,
  onStatusChange,
  onShowDetail,
  onCloseDetail,
  onNextPage,
}) {
  const totals = summary || { succeeded: 0, in_progress: 0, failed: 0, updated_at: null }
  const filters = [
    ['', '全部'],
    ['succeeded', '成功'],
    ['in_progress', '进行中'],
    ['failed', '失败'],
  ]

  return (
    <main className="knowledge-view">
      <div className="knowledge-page">
        <div className="page-heading">
          <div>
            <span className="eyebrow">企业共享知识库</span>
            <h1>知识文档</h1>
          </div>
        </div>

        <div className="knowledge-summary" aria-label="知识库摘要">
          <div className="summary-item"><span className="summary-dot summary-dot-ready" /><div><strong>{totals.succeeded}</strong><span>成功</span></div></div>
          <div className="summary-item"><span className="summary-dot summary-dot-running" /><div><strong>{totals.in_progress}</strong><span>进行中</span></div></div>
          <div className="summary-item"><span className="summary-dot summary-dot-failed" /><div><strong>{totals.failed}</strong><span>失败</span></div></div>
          <p>最近更新：{formatTime(totals.updated_at)}</p>
        </div>

        <div className="library-toolbar">
          <label className="search-field">
            <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5.5" /><path d="m13.2 13.2 3.3 3.3" /></svg>
            <input
              type="search"
              value={search}
              placeholder="搜索文档名称"
              onChange={event => onSearch(event.target.value)}
            />
          </label>
          <div className="filter-group" aria-label="状态筛选">
            {filters.map(([value, label]) => (
              <button
                className={`filter-chip ${status === value ? 'is-active' : ''}`}
                type="button"
                key={value || 'all'}
                onClick={() => onStatusChange(value)}
              >{label}</button>
            ))}
          </div>
        </div>

        <div className="document-panel">
          <div className="document-head document-grid" aria-hidden="true">
            <span>序号</span><span>文件名</span><span>大小</span><span>入库状态</span><span>更新时间</span><span>操作</span>
          </div>
          <div className="document-list">
            {documents.map(document => (
              <article className="document-row document-grid" key={document.id}>
                <span className="serial-number">{document.sequence}</span>
                <div className="document-primary"><strong>《{document.filename}》</strong></div>
                <span className="file-size-text">{formatSize(document.size_bytes)}</span>
                <span className={`status-pill status-${document.status}`}>{STATUS_LABELS[document.status]}</span>
                <span className="updated-text">{formatTime(document.updated_at)}</span>
                <div className="row-actions">
                  <button className="row-action" type="button" onClick={() => onShowDetail(document.id)}>详情</button>
                </div>
              </article>
            ))}
          </div>
          {!loading && documents.length === 0 && (
            <div className="document-empty">
              <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M6 6h20v20H6zM10 12h12M10 17h8" /></svg>
              <strong>没有找到匹配的文档</strong>
              <span>请修改搜索词或状态筛选。</span>
            </div>
          )}
          {loading && <div className="document-feedback">正在读取知识文档…</div>}
          {error && <div className="document-feedback document-error" role="alert">{error}</div>}
        </div>
        {nextCursor && !loading && (
          <button className="next-page-button" type="button" onClick={onNextPage}>加载更多</button>
        )}
      </div>

      {detail && (
        <div className="knowledge-detail-backdrop" role="presentation" onMouseDown={onCloseDetail}>
          <section className="knowledge-detail" role="dialog" aria-modal="true" aria-labelledby="knowledge-detail-title" onMouseDown={event => event.stopPropagation()}>
            <div className="knowledge-detail-header">
              <div><span className="eyebrow">文档详情</span><h2 id="knowledge-detail-title">《{detail.original_filename}》</h2></div>
              <button type="button" aria-label="关闭详情" onClick={onCloseDetail}>×</button>
            </div>
            <div className="knowledge-detail-grid">
              <DetailItem label="文件大小">{formatSize(detail.size_bytes)}</DetailItem>
              <DetailItem label="上传人">{detail.uploaded_by.display_name}</DetailItem>
              <DetailItem label="上传时间">{formatTime(detail.uploaded_at)}</DetailItem>
              <DetailItem label="当前版本">{detail.current_version ? `v${detail.current_version.number}` : '尚无可用版本'}</DetailItem>
              <DetailItem label="最新任务">{detail.latest_task ? TASK_STATE_LABELS[detail.latest_task.state] : '暂无任务'}</DetailItem>
              <DetailItem label="任务结果">{detail.latest_task?.result_message || '暂无补充说明'}</DetailItem>
            </div>
          </section>
        </div>
      )}
    </main>
  )
}

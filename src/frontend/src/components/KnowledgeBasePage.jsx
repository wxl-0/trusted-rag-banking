import UploadDocumentModal from './UploadDocumentModal'
import DeleteConfirmDialog from './DeleteConfirmDialog'


const STATUS_LABELS = {
  succeeded: '成功',
  in_progress: '进行中',
  failed: '失败',
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function formatUpdateTime(value) {
  if (!value) return '暂无更新'
  const date = new Date(value)
  const now = new Date()
  if (Number.isNaN(date.getTime())) return '暂无更新'
  const isToday = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
  if (isToday) {
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    return `${hours}:${minutes}`
  }
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function paginationItems(currentPage, totalPages) {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1)
  let start = Math.max(2, currentPage - 1)
  let end = Math.min(totalPages - 1, currentPage + 1)
  if (currentPage <= 4) end = 5
  if (currentPage >= totalPages - 3) start = totalPages - 4
  return [
    1,
    ...(start > 2 ? ['start-ellipsis'] : []),
    ...Array.from({ length: end - start + 1 }, (_, index) => start + index),
    ...(end < totalPages - 1 ? ['end-ellipsis'] : []),
    totalPages,
  ]
}


export default function KnowledgeBasePage({
  summary,
  documents,
  loading,
  error,
  search,
  status,
  page = 1,
  pageSize = 10,
  total = 0,
  uploadOpen = false,
  uploadItems = [],
  uploadLoading = false,
  uploadStarted = false,
  uploadError = '',
  deleteTarget = null,
  deleteLoading = false,
  onSearch,
  onStatusChange,
  onDownload,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
  onPageChange,
  onOpenUpload,
  onCloseUpload,
  onAddUploadFiles,
  onRemoveUploadFile,
  onSubmitUpload,
}) {
  const totals = summary || { succeeded: 0, in_progress: 0, failed: 0, updated_at: null }
  const filters = [
    ['', '全部'],
    ['succeeded', '成功'],
    ['in_progress', '进行中'],
    ['failed', '失败'],
  ]
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <main className="knowledge-view">
      <div className="knowledge-page">
        <div className="page-heading">
          <div>
            <span className="eyebrow">企业共享知识库</span>
            <h1>知识文档</h1>
          </div>
          <button className="primary-button upload-button" type="button" onClick={onOpenUpload}>
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 14V3M6 7l4-4 4 4" /><path d="M4 12v4h12v-4" /></svg>
            上传知识文档
          </button>
        </div>

        <div className="knowledge-summary" aria-label="知识库摘要">
          <div className="summary-item"><span className="summary-dot summary-dot-ready" /><div><strong>{totals.succeeded}</strong><span>成功</span></div></div>
          <div className="summary-item"><span className="summary-dot summary-dot-running" /><div><strong>{totals.in_progress}</strong><span>进行中</span></div></div>
          <div className="summary-item"><span className="summary-dot summary-dot-failed" /><div><strong>{totals.failed}</strong><span>失败</span></div></div>
          <p>最近更新：{formatUpdateTime(totals.updated_at)}</p>
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
                <div className="document-primary" data-full-name={`《${document.filename}》`}><strong>《{document.filename}》</strong></div>
                <span className="file-size-text">{formatSize(document.size_bytes)}</span>
                <span className={`status-pill status-${document.status}`}>{STATUS_LABELS[document.status]}</span>
                <span className="updated-text">{formatUpdateTime(document.updated_at)}</span>
                <div className="row-actions">
                  <button className="row-action" type="button" onClick={() => onDownload(document)}>下载</button>
                  <button className="row-action row-action-delete" type="button" onClick={() => onRequestDelete(document)}>删除</button>
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
        {total > 0 && !loading && (
          <nav className="document-pagination" aria-label="知识文档分页">
            <span className="pagination-total">共 {total} 篇</span>
            <div>
              <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</button>
              {paginationItems(page, totalPages).map(item => (
                typeof item === 'number' ? (
                  <button
                    className={item === page ? 'is-active' : ''}
                    type="button"
                    key={item}
                    aria-label={`第 ${item} 页`}
                    aria-current={item === page ? 'page' : undefined}
                    onClick={() => onPageChange(item)}
                  >{item}</button>
                ) : <span className="pagination-ellipsis" key={item}>…</span>
              ))}
              <button type="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>下一页</button>
            </div>
          </nav>
        )}
      </div>

      {uploadOpen && (
        <UploadDocumentModal
          items={uploadItems}
          loading={uploadLoading}
          started={uploadStarted}
          error={uploadError}
          onClose={onCloseUpload}
          onAddFiles={onAddUploadFiles}
          onRemoveFile={onRemoveUploadFile}
          onSubmit={onSubmitUpload}
        />
      )}
      {deleteTarget && (
        <DeleteConfirmDialog
          title="删除知识文档？"
          beforeName="这会删除《"
          name={deleteTarget.filename}
          afterName="》"
          loading={deleteLoading}
          onCancel={onCancelDelete}
          onConfirm={onConfirmDelete}
        />
      )}
    </main>
  )
}

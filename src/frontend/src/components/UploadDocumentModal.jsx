import {
  MAX_UPLOAD_BATCH_BYTES,
  MAX_UPLOAD_FILES,
} from '../uploadBatch'


const STATUS_LABELS = {
  ready: '待上传',
  uploading: '正在提交',
  accepted: '已受理',
  validation_failed: '校验失败',
  submission_failed: '提交失败',
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}


export default function UploadDocumentModal({
  items,
  loading,
  started,
  error,
  onClose,
  onAddFiles,
  onRemoveFile,
  onSubmit,
}) {
  const totalBytes = items.reduce((sum, item) => sum + item.file.size, 0)
  const readyCount = items.filter(item => item.status === 'ready').length
  const completedCount = items.filter(item => (
    item.status === 'accepted'
    || item.status === 'validation_failed'
    || item.status === 'submission_failed'
  )).length
  const overBatchLimit = totalBytes > MAX_UPLOAD_BATCH_BYTES
  const chooseDroppedFiles = event => {
    event.preventDefault()
    if (!started && event.dataTransfer.files.length) onAddFiles(event.dataTransfer.files)
  }
  const selectFiles = event => {
    if (event.target.files.length) onAddFiles(event.target.files)
    event.target.value = ''
  }

  return (
    <div className="upload-backdrop" role="presentation" onMouseDown={loading ? undefined : onClose}>
      <section className="upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title" onMouseDown={event => event.stopPropagation()}>
        <div className="upload-modal-header">
          <div><span className="eyebrow">企业共享知识库</span><h2 id="upload-title">上传知识文档</h2></div>
          <button type="button" onClick={onClose} disabled={loading} aria-label="关闭上传弹窗">×</button>
        </div>

        <div className="upload-step">
          <label
            className={`drop-zone ${items.length ? 'drop-zone-compact' : ''} ${started ? 'is-disabled' : ''}`}
            onDragOver={event => event.preventDefault()}
            onDrop={chooseDroppedFiles}
          >
            <span className="upload-illustration">
              <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M6 4h13l7 7v17H6V4Z" /><path d="M19 4v7h7M16 23V13M12 17l4-4 4 4" /></svg>
            </span>
            <span className="drop-zone-copy">
              <strong>{items.length ? '继续添加文件' : '拖放文件到这里，或点击选择'}</strong>
              <span>{items.length ? `最多 ${MAX_UPLOAD_FILES} 个文件，总计不超过 200 MiB` : '支持 DOC、DOCX、PDF、XLS、XLSX，单个文件不超过 50 MiB'}</span>
            </span>
            <input
              type="file"
              multiple
              accept=".doc,.docx,.pdf,.xls,.xlsx"
              disabled={started}
              onChange={selectFiles}
            />
          </label>

          {items.length > 0 && (
            <div className="upload-file-list" aria-label="待上传文件">
              {items.map(item => (
                <div className="selected-file" key={item.id}>
                  <span className="selected-file-mark">{item.file.name.split('.').pop()?.toUpperCase()}</span>
                  <div className="selected-file-copy">
                    <strong title={item.file.name}>{item.file.name}</strong>
                    <span>{formatSize(item.file.size)}{item.message ? ` · ${item.message}` : ''}</span>
                  </div>
                  <span className={`upload-file-status upload-file-status-${item.status}`}>
                    {STATUS_LABELS[item.status]}
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemoveFile(item.id)}
                    disabled={started}
                    aria-label={`移除${item.file.name}`}
                  >×</button>
                </div>
              ))}
            </div>
          )}
          {overBatchLimit && !started && (
            <div className="upload-error" role="alert">所选文件总大小不能超过 200 MiB，请移除部分文件</div>
          )}
          {error && <div className="upload-error" role="alert">{error}</div>}
        </div>

        <div className="upload-modal-footer">
          <div className="upload-selection-summary">
            <strong>已选 {items.length} 个文件</strong>
            <span>共 {formatSize(totalBytes)}</span>
          </div>
          {!started && <button className="secondary-button" type="button" onClick={onClose}>取消</button>}
          <button
            className="primary-button"
            type="button"
            onClick={started && !loading ? onClose : onSubmit}
            disabled={loading || (!started && (!readyCount || overBatchLimit))}
          >
            {loading
              ? `正在上传 ${completedCount}/${items.length}`
              : started ? '完成' : '开始上传'}
          </button>
        </div>
      </section>
    </div>
  )
}

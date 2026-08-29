function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}


export default function UploadDocumentModal({
  file,
  loading,
  error,
  onClose,
  onSelectFile,
  onSubmit,
}) {
  const chooseDroppedFile = event => {
    event.preventDefault()
    if (event.dataTransfer.files.length) onSelectFile(event.dataTransfer.files[0])
  }

  return (
    <div className="upload-backdrop" role="presentation" onMouseDown={loading ? undefined : onClose}>
      <section className="upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title" onMouseDown={event => event.stopPropagation()}>
        <div className="upload-modal-header">
          <div><span className="eyebrow">企业共享知识库</span><h2 id="upload-title">上传知识文档</h2></div>
          <button type="button" onClick={onClose} disabled={loading} aria-label="关闭上传弹窗">×</button>
        </div>

        <div className="upload-step">
          <label className="drop-zone" onDragOver={event => event.preventDefault()} onDrop={chooseDroppedFile}>
            <span className="upload-illustration">
              <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M6 4h13l7 7v17H6V4Z" /><path d="M19 4v7h7M16 23V13M12 17l4-4 4 4" /></svg>
            </span>
            <strong>拖放文件到这里，或点击选择</strong>
            <span>支持 DOC、DOCX、PDF、XLS、XLSX，单个文件默认不超过 50 MiB</span>
            <input
              type="file"
              accept=".doc,.docx,.pdf,.xls,.xlsx"
              onChange={event => onSelectFile(event.target.files[0] || null)}
            />
          </label>

          {file && (
            <div className="selected-file">
              <span className="selected-file-mark">{file.name.split('.').pop()?.toUpperCase()}</span>
              <div><strong>{file.name}</strong><span>{formatSize(file.size)}</span></div>
              <button type="button" onClick={() => onSelectFile(null)} disabled={loading} aria-label="移除文件">×</button>
            </div>
          )}
          {error && <div className="upload-error" role="alert">{error}</div>}
        </div>

        <div className="upload-modal-footer">
          <button className="secondary-button" type="button" onClick={onClose} disabled={loading}>取消</button>
          <button className="primary-button" type="button" onClick={onSubmit} disabled={!file || loading}>
            {loading ? '正在提交…' : '开始入库'}
          </button>
        </div>
      </section>
    </div>
  )
}

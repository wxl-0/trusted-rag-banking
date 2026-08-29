import { keepFocusInDialog, useDialogFocus } from './dialogFocus'


export default function DeleteConfirmDialog({
  title,
  name,
  beforeName,
  afterName,
  loading = false,
  onCancel,
  onConfirm,
}) {
  const dialogRef = useDialogFocus()

  return (
    <div className="confirm-overlay" role="presentation">
      <section
        ref={dialogRef}
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-confirm-title"
        aria-describedby="delete-confirm-message"
        tabIndex="-1"
        onKeyDown={event => {
          if (event.key === 'Escape' && !loading) {
            event.preventDefault()
            onCancel()
            return
          }
          keepFocusInDialog(event, dialogRef.current)
        }}
      >
        <h2 id="delete-confirm-title">{title}</h2>
        <p className="confirm-message" id="delete-confirm-message">
          {beforeName}<strong>{name}</strong>{afterName}
        </p>
        <div className="confirm-actions">
          <button type="button" disabled={loading} onClick={onCancel}>取消</button>
          <button className="danger" type="button" disabled={loading} onClick={onConfirm}>删除</button>
        </div>
      </section>
    </div>
  )
}

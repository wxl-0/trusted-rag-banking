import { useEffect, useState } from 'react'
import DeleteConfirmDialog from './DeleteConfirmDialog'


export default function ConversationSidebar({
  conversations,
  currentId,
  collapsed,
  activeView = 'chat',
  showKnowledgeBase = false,
  onNew,
  onSelect,
  onSearch,
  onRename,
  onDelete,
  onShowKnowledgeBase,
}) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [menuId, setMenuId] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [draft, setDraft] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)

  useEffect(() => {
    if (menuId === null) return undefined

    const closeMenu = () => setMenuId(null)
    document.addEventListener('click', closeMenu)
    return () => document.removeEventListener('click', closeMenu)
  }, [menuId])

  if (collapsed) return null

  const startRename = conversation => {
    setEditingId(conversation.id)
    setDraft(conversation.title)
    setMenuId(null)
  }

  const submitRename = async conversation => {
    if (draft.trim() && draft.trim() !== conversation.title) {
      await onRename(conversation.id, draft.trim())
    }
    setEditingId(null)
  }

  const selectConversation = conversationId => {
    setMenuId(null)
    onSelect(conversationId)
  }

  return (
    <aside className="conversation-sidebar" aria-label="对话导航">
      <div className="sidebar-header">
        <button className="sidebar-brand" type="button" onClick={onNew}>
          <img src="/logo.png" alt="" />
          <span>监管制度智能问答</span>
        </button>
        <button
          className="sidebar-icon-button"
          type="button"
          aria-label="搜索历史对话"
          aria-expanded={searchOpen}
          onClick={() => setSearchOpen(value => !value)}
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <circle cx="8.5" cy="8.5" r="5.5" />
            <path d="m12.7 12.7 3.8 3.8" />
          </svg>
        </button>
      </div>
      {searchOpen && (
        <label className="history-search">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <circle cx="8.5" cy="8.5" r="5.5" />
            <path d="m12.7 12.7 3.8 3.8" />
          </svg>
          <input
            type="search"
            autoFocus
            placeholder="搜索对话"
            onChange={event => onSearch(event.target.value)}
          />
        </label>
      )}
      <nav className="sidebar-primary" aria-label="主要功能">
        <button className={`sidebar-nav-item ${activeView === 'chat' && !currentId ? 'is-active' : ''}`} type="button" onClick={onNew}>
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M4 4.5h12v9H9l-4 3v-3H4v-9Z" />
            <path d="M10 7v4M8 9h4" />
          </svg>
          <span>新对话</span>
        </button>
        {showKnowledgeBase && (
          <button
            className={`sidebar-nav-item ${activeView === 'knowledge' ? 'is-active' : ''}`}
            type="button"
            onClick={onShowKnowledgeBase}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M3.5 5.5 10 3l6.5 2.5L10 8 3.5 5.5Z" />
              <path d="M3.5 5.5v7L10 15l6.5-2.5v-7M10 8v7" />
            </svg>
            <span>知识库管理</span>
          </button>
        )}
      </nav>
      <div className="sidebar-history">
        <span className="sidebar-section-label">最近</span>
        {conversations.map(conversation => (
          <div
            className={`history-item ${activeView === 'chat' && conversation.id === currentId ? 'is-active' : ''} ${editingId === conversation.id ? 'is-renaming' : ''}`}
            key={conversation.id}
          >
            {editingId === conversation.id ? (
              <input
                className="history-rename-input"
                value={draft}
                autoFocus
                onChange={event => setDraft(event.target.value)}
                onBlur={() => submitRename(conversation)}
                onKeyDown={event => {
                  if (event.key === 'Enter') event.currentTarget.blur()
                  if (event.key === 'Escape') setEditingId(null)
                }}
              />
            ) : (
              <button
                className="history-open"
                type="button"
                onClick={() => selectConversation(conversation.id)}
              >{conversation.title}</button>
            )}
            <button
              className="history-more"
              type="button"
              aria-label="管理对话"
              aria-expanded={menuId === conversation.id}
              onClick={event => {
                event.stopPropagation()
                setMenuId(menuId === conversation.id ? null : conversation.id)
              }}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <circle cx="4" cy="10" r="1" />
                <circle cx="10" cy="10" r="1" />
                <circle cx="16" cy="10" r="1" />
              </svg>
            </button>
            {menuId === conversation.id && (
              <div className="history-menu">
                <button type="button" onClick={() => startRename(conversation)}>重命名</button>
                <button type="button" className="danger" onClick={() => {
                  setDeleteTarget(conversation)
                  setMenuId(null)
                }}>删除</button>
              </div>
            )}
          </div>
        ))}
        {conversations.length === 0 && <div className="history-empty">没有对话</div>}
      </div>
      {deleteTarget && (
        <DeleteConfirmDialog
          title="删除对话？"
          beforeName="这会删除“"
          name={deleteTarget.title || '新对话'}
          afterName="”"
          onCancel={() => setDeleteTarget(null)}
          onConfirm={async () => {
            await onDelete(deleteTarget.id)
            setDeleteTarget(null)
          }}
        />
      )}
    </aside>
  )
}

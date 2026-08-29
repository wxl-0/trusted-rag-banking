import { useEffect, useState } from 'react'
import MessageList from './components/MessageList'
import ChatInput from './components/ChatInput'
import ConversationSidebar from './components/ConversationSidebar'
import KnowledgeBasePage from './components/KnowledgeBasePage'
import {
  askQuestionStream,
  createConversation,
  deleteConversation,
  deleteKnowledgeDocument,
  fetchConversation,
  fetchIdentity,
  fetchKnowledgeDocument,
  fetchKnowledgeSummary,
  listConversations,
  listKnowledgeDocuments,
  renameConversation,
  toDisplayMessages,
  uploadKnowledgeDocument,
} from './api/client'
import { getUserManager, initializeAuthentication } from './auth/client'
import { businessRoleLabel, identityInitial } from './auth/config'


const ACTIVE_CONVERSATION_KEY = 'trusted-rag.active-conversation-id'

function LoginScreen({ loading, error, onLogin }) {
  return (
    <section className="login-screen">
      <header className="login-brand">
        <img src="/logo.png" alt="南京银行" />
        <span>监管制度智能问答</span>
      </header>
      <main className="login-main">
        <div className="login-orbit" aria-hidden="true">
          <span className="orbit-ring orbit-ring-one" />
          <span className="orbit-ring orbit-ring-two" />
          <span className="orbit-mark">
            <svg viewBox="0 0 32 32">
              <path d="M16 3.5 26 7.7v7.4c0 6.7-4 11.4-10 13.6-6-2.2-10-6.9-10-13.6V7.7L16 3.5Z" />
              <path d="m11.3 15.9 3.1 3.1 6.5-7" />
            </svg>
          </span>
        </div>
        <div className="login-copy">
          <span className="login-eyebrow">企业监管知识工作台</span>
          <h1>让每一次制度查询<br />都有原文依据</h1>
          <p>使用企业账号访问统一维护的监管制度、统计报表与可信证据。</p>
        </div>
        <button type="button" className="login-button" onClick={onLogin} disabled={loading}>
          <span>{loading ? '正在连接身份服务…' : '企业账号登录'}</span>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7.5 4.5 5.5 5.5-5.5 5.5" /></svg>
        </button>
        {error && <div className="login-error" role="alert">{error}</div>}
        <div className="identity-note">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <rect x="4" y="8" width="12" height="9" rx="2" />
            <path d="M6.5 8V6.5a3.5 3.5 0 0 1 7 0V8" />
          </svg>
          身份认证与登录会话由 Keycloak 提供
        </div>
      </main>
      <footer className="login-footer">企业共享知识库 · 仅限授权成员访问</footer>
    </section>
  )
}


function AccountMenu({ identity, onLogout }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="account-area">
      <button
        type="button"
        className="account-button"
        aria-expanded={open}
        onClick={() => setOpen(value => !value)}
      >
        <span className="account-avatar">{identityInitial(identity)}</span>
        <span className="account-copy">
          <strong>{identity.display_name}</strong>
          <small>{businessRoleLabel(identity.business_role)}</small>
        </span>
        <svg className="account-chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="m6 8 4 4 4-4" /></svg>
      </button>
      {open && (
        <div className="account-menu">
          <div className="account-profile">
            <span className="account-avatar">{identityInitial(identity)}</span>
            <div>
              <strong>{identity.display_name}</strong>
              <span>{identity.email || identity.username}</span>
            </div>
          </div>
          <div className="account-menu-divider" />
          <button type="button" onClick={onLogout}>
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8 4H4.5v12H8M12 6l4 4-4 4M7 10h9" /></svg>
            退出登录
          </button>
        </div>
      )}
    </div>
  )
}


export default function App() {
  const [authLoading, setAuthLoading] = useState(true)
  const [authError, setAuthError] = useState('')
  const [user, setUser] = useState(null)
  const [identity, setIdentity] = useState(null)
  const [conversationId, setConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [conversations, setConversations] = useState([])
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [activeView, setActiveView] = useState('chat')
  const [knowledgeSummary, setKnowledgeSummary] = useState(null)
  const [knowledgeDocuments, setKnowledgeDocuments] = useState([])
  const [knowledgePage, setKnowledgePage] = useState(1)
  const [knowledgeTotal, setKnowledgeTotal] = useState(0)
  const [knowledgeSearch, setKnowledgeSearch] = useState('')
  const [knowledgeStatus, setKnowledgeStatus] = useState('')
  const [knowledgeDetail, setKnowledgeDetail] = useState(null)
  const [knowledgeLoading, setKnowledgeLoading] = useState(false)
  const [knowledgeError, setKnowledgeError] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [knowledgeDeleteTarget, setKnowledgeDeleteTarget] = useState(null)
  const [knowledgeDeleteLoading, setKnowledgeDeleteLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    initializeAuthentication()
      .then(async ({ user: authenticatedUser }) => {
        if (cancelled || !authenticatedUser) return
        const authenticatedIdentity = await fetchIdentity(authenticatedUser.access_token)
        const activeConversationId = window.localStorage.getItem(
          ACTIVE_CONVERSATION_KEY,
        )
        let restoredConversation = null
        if (activeConversationId) {
          restoredConversation = await fetchConversation(
            activeConversationId,
            authenticatedUser.access_token,
          )
          if (!restoredConversation) {
            window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY)
          }
        }
        if (!cancelled) {
          setUser(authenticatedUser)
          setIdentity(authenticatedIdentity)
          const history = await listConversations('', null, authenticatedUser.access_token)
          setConversations(history.items)
          if (restoredConversation) {
            setConversationId(restoredConversation.id)
            setMessages(toDisplayMessages(restoredConversation.messages))
          }
        }
      })
      .catch(() => {
        if (!cancelled) setAuthError('登录状态读取失败，请重新登录')
      })
      .finally(() => {
        if (!cancelled) setAuthLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const login = async () => {
    const manager = getUserManager()
    if (!manager) {
      setAuthError('尚未配置 Keycloak 登录地址')
      return
    }
    setAuthLoading(true)
    await manager.signinRedirect()
  }

  const logout = async () => {
    setMessages([])
    setConversationId(null)
    await getUserManager()?.signoutRedirect()
  }

  const refreshHistory = async (search = '') => {
    const history = await listConversations(search, null, user.access_token)
    setConversations(history.items)
  }

  const newConversation = () => {
    setActiveView('chat')
    setConversationId(null)
    setMessages([])
    window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY)
  }

  const selectConversation = async id => {
    const conversation = await fetchConversation(id, user.access_token)
    if (!conversation) return refreshHistory()
    setActiveView('chat')
    setConversationId(id)
    setMessages(toDisplayMessages(conversation.messages))
    window.localStorage.setItem(ACTIVE_CONVERSATION_KEY, id)
  }

  const handleRename = async (id, title) => {
    await renameConversation(id, title, user.access_token)
    await refreshHistory()
  }

  const handleDelete = async id => {
    await deleteConversation(id, user.access_token)
    if (id === conversationId) newConversation()
    await refreshHistory()
  }

  const loadKnowledgeDocuments = async ({
    search = knowledgeSearch,
    status = knowledgeStatus,
    page = knowledgePage,
  } = {}) => {
    setKnowledgeLoading(true)
    setKnowledgeError('')
    try {
      const result = await listKnowledgeDocuments({
        search,
        status,
        page,
        limit: 10,
        accessToken: user.access_token,
      })
      setKnowledgeDocuments(result.items)
      setKnowledgePage(result.page)
      setKnowledgeTotal(result.total)
    } catch (error) {
      setKnowledgeError(error.message)
    } finally {
      setKnowledgeLoading(false)
    }
  }

  const showKnowledgeBase = async () => {
    if (identity.business_role !== 'knowledge_maintainer') return
    setActiveView('knowledge')
    setKnowledgeDetail(null)
    setKnowledgeLoading(true)
    setKnowledgeError('')
    try {
      const [summary, result] = await Promise.all([
        fetchKnowledgeSummary(user.access_token),
        listKnowledgeDocuments({ page: 1, limit: 10, accessToken: user.access_token }),
      ])
      setKnowledgeSummary(summary)
      setKnowledgeDocuments(result.items)
      setKnowledgePage(result.page)
      setKnowledgeTotal(result.total)
    } catch (error) {
      setKnowledgeError(error.message)
    } finally {
      setKnowledgeLoading(false)
    }
  }

  const searchKnowledgeDocuments = value => {
    setKnowledgeSearch(value)
    loadKnowledgeDocuments({ search: value, page: 1 })
  }

  const filterKnowledgeDocuments = value => {
    setKnowledgeStatus(value)
    loadKnowledgeDocuments({ status: value, page: 1 })
  }

  const showKnowledgeDocument = async documentId => {
    setKnowledgeError('')
    try {
      setKnowledgeDetail(await fetchKnowledgeDocument(documentId, user.access_token))
    } catch (error) {
      setKnowledgeError(error.message)
    }
  }

  const openUpload = () => {
    setUploadFile(null)
    setUploadError('')
    setUploadOpen(true)
  }

  const closeUpload = () => {
    if (uploadLoading) return
    setUploadOpen(false)
    setUploadFile(null)
    setUploadError('')
  }

  const submitUpload = async () => {
    if (!uploadFile || uploadLoading) return
    setUploadLoading(true)
    setUploadError('')
    try {
      await uploadKnowledgeDocument(uploadFile, user.access_token)
      const [summary, result] = await Promise.all([
        fetchKnowledgeSummary(user.access_token),
        listKnowledgeDocuments({ page: 1, limit: 10, accessToken: user.access_token }),
      ])
      setKnowledgeSummary(summary)
      setKnowledgeDocuments(result.items)
      setKnowledgePage(result.page)
      setKnowledgeTotal(result.total)
      setKnowledgeSearch('')
      setKnowledgeStatus('')
      setUploadOpen(false)
      setUploadFile(null)
    } catch (error) {
      setUploadError(error.message)
    } finally {
      setUploadLoading(false)
    }
  }

  const confirmKnowledgeDocumentDelete = async () => {
    if (!knowledgeDeleteTarget || knowledgeDeleteLoading) return
    setKnowledgeDeleteLoading(true)
    setKnowledgeError('')
    try {
      const requestId = window.crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`
      await deleteKnowledgeDocument(
        knowledgeDeleteTarget.id,
        user.access_token,
        requestId,
      )
      const targetPage = knowledgeDocuments.length === 1 && knowledgePage > 1
        ? knowledgePage - 1
        : knowledgePage
      const [summary, result] = await Promise.all([
        fetchKnowledgeSummary(user.access_token),
        listKnowledgeDocuments({
          search: knowledgeSearch,
          status: knowledgeStatus,
          page: targetPage,
          limit: 10,
          accessToken: user.access_token,
        }),
      ])
      setKnowledgeSummary(summary)
      setKnowledgeDocuments(result.items)
      setKnowledgePage(result.page)
      setKnowledgeTotal(result.total)
      if (knowledgeDetail?.id === knowledgeDeleteTarget.id) setKnowledgeDetail(null)
    } catch (error) {
      setKnowledgeError(error.message)
    } finally {
      setKnowledgeDeleteTarget(null)
      setKnowledgeDeleteLoading(false)
    }
  }

  const handleSend = async (question) => {
    const newMessages = [...messages, { role: 'user', content: question }]
    const requestId = window.crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`
    setMessages([...newMessages, {
      role: 'assistant',
      requestId,
      content: {
        processing: true,
        stage: 'connecting',
        message: '正在提交问题',
        startedAt: Date.now(),
      },
    }])
    setLoading(true)

    try {
      let activeConversationId = conversationId
      if (!activeConversationId) {
        const conversation = await createConversation(user.access_token)
        activeConversationId = conversation.id
        setConversationId(activeConversationId)
        window.localStorage.setItem(
          ACTIVE_CONVERSATION_KEY,
          activeConversationId,
        )
      }

      const result = await askQuestionStream({
        question,
        conversationId: activeConversationId,
        requestId,
        onEvent: (event, data) => {
          if (event !== 'progress') return
          setMessages(prev => prev.map(message => (
            message.requestId === requestId
              ? { ...message, content: { ...message.content, ...data } }
              : message
          )))
        },
        accessToken: user.access_token,
      })
      setMessages(prev => prev.map(message => (
        message.requestId === requestId
          ? { role: 'assistant', content: result }
          : message
      )))
      const restored = await fetchConversation(
        activeConversationId,
        user.access_token,
      )
      if (restored) setMessages(toDisplayMessages(restored.messages))
      await refreshHistory()
    } catch (err) {
      setMessages(prev => prev.map(message => (
        message.requestId === requestId
          ? {
              role: 'assistant',
              content: { answer: '', evidence: [], refuse_reason: err.message },
            }
          : message
      )))
    } finally {
      setLoading(false)
    }
  }

  if (!user || !identity) {
    return <LoginScreen loading={authLoading} error={authError} onLogin={login} />
  }

  const currentConversationTitle = conversations.find(
    conversation => conversation.id === conversationId,
  )?.title || '新对话'

  return (
    <div className="workspace-layout">
      <ConversationSidebar
        conversations={conversations}
        currentId={conversationId}
        collapsed={sidebarCollapsed}
        activeView={activeView}
        showKnowledgeBase={identity.business_role === 'knowledge_maintainer'}
        onNew={newConversation}
        onSelect={selectConversation}
        onSearch={refreshHistory}
        onRename={handleRename}
        onDelete={handleDelete}
        onShowKnowledgeBase={showKnowledgeBase}
      />
      <div className="workspace-content">
        <header className="topbar">
          <div className="topbar-inner">
            <div className="main-header-left">
              <button
                className="sidebar-toggle"
                type="button"
                aria-label={sidebarCollapsed ? '展开对话侧栏' : '收起对话侧栏'}
                aria-expanded={!sidebarCollapsed}
                onClick={() => setSidebarCollapsed(value => !value)}
              >
                <svg viewBox="0 0 20 20" aria-hidden="true">
                  <rect x="3" y="3.5" width="14" height="13" rx="2" />
                  <path d="M7.5 3.5v13" />
                </svg>
              </button>
              <div className="view-context">
                <strong>{activeView === 'knowledge' ? '知识库管理' : '问答'}</strong>
                <span>{activeView === 'knowledge' ? '企业共享知识库' : currentConversationTitle}</span>
              </div>
            </div>
            <AccountMenu identity={identity} onLogout={logout} />
          </div>
        </header>
        {activeView === 'knowledge' ? (
          <KnowledgeBasePage
            summary={knowledgeSummary}
            documents={knowledgeDocuments}
            detail={knowledgeDetail}
            loading={knowledgeLoading}
            error={knowledgeError}
            search={knowledgeSearch}
            status={knowledgeStatus}
            page={knowledgePage}
            pageSize={10}
            total={knowledgeTotal}
            uploadOpen={uploadOpen}
            uploadFile={uploadFile}
            uploadLoading={uploadLoading}
            uploadError={uploadError}
            deleteTarget={knowledgeDeleteTarget}
            deleteLoading={knowledgeDeleteLoading}
            onSearch={searchKnowledgeDocuments}
            onStatusChange={filterKnowledgeDocuments}
            onShowDetail={showKnowledgeDocument}
            onRequestDelete={setKnowledgeDeleteTarget}
            onCancelDelete={() => setKnowledgeDeleteTarget(null)}
            onConfirmDelete={confirmKnowledgeDocumentDelete}
            onCloseDetail={() => setKnowledgeDetail(null)}
            onPageChange={page => loadKnowledgeDocuments({ page })}
            onOpenUpload={openUpload}
            onCloseUpload={closeUpload}
            onSelectUploadFile={setUploadFile}
            onSubmitUpload={submitUpload}
          />
        ) : (
          <>
            <MessageList messages={messages} />
            <ChatInput onSend={handleSend} loading={loading} />
          </>
        )}
      </div>
    </div>
  )
}

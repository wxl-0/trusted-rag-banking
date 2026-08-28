import { useEffect, useState } from 'react'
import MessageList from './components/MessageList'
import ChatInput from './components/ChatInput'
import { askQuestionStream, buildHistory, fetchIdentity } from './api/client'
import { getUserManager, initializeAuthentication } from './auth/client'
import { businessRoleLabel, identityInitial } from './auth/config'


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
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    initializeAuthentication()
      .then(async ({ user: authenticatedUser }) => {
        if (cancelled || !authenticatedUser) return
        const authenticatedIdentity = await fetchIdentity(authenticatedUser.access_token)
        if (!cancelled) {
          setUser(authenticatedUser)
          setIdentity(authenticatedIdentity)
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
    await getUserManager()?.signoutRedirect()
  }

  const handleSend = async (question) => {
    const newMessages = [...messages, { role: 'user', content: question }]
    const requestId = `${Date.now()}-${Math.random()}`
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
      const result = await askQuestionStream(
        question,
        null,
        buildHistory(messages),
        (event, data) => {
          if (event !== 'progress') return
          setMessages(prev => prev.map(message => (
            message.requestId === requestId
              ? { ...message, content: { ...message.content, ...data } }
              : message
          )))
        },
        user.access_token,
      )
      setMessages(prev => prev.map(message => (
        message.requestId === requestId
          ? { role: 'assistant', content: result }
          : message
      )))
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

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-brand">
          <img src="/logo.png" alt="南京银行" />
          <span className="header-title">监管制度智能问答</span>
        </div>
        <AccountMenu identity={identity} onLogout={logout} />
      </header>
      <MessageList messages={messages} />
      <ChatInput onSend={handleSend} loading={loading} />
    </div>
  )
}

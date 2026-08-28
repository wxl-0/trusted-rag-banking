const state = {
  role: 'member',
  view: 'chat',
  currentConversation: null,
  sidebarCollapsed: false,
  statusFilter: 'all',
  selectedFile: null,
  uploadTimers: [],
  pendingDeletion: null,
}

const users = {
  member: {
    name: '林然',
    avatar: '林',
    role: '企业成员',
    email: 'linran@example.com',
  },
  maintainer: {
    name: '王芳',
    avatar: '王',
    role: '知识库维护者',
    email: 'wangfang@example.com',
  },
}

const $ = selector => document.querySelector(selector)
const $$ = selector => [...document.querySelectorAll(selector)]

const loginScreen = $('[data-screen="login"]')
const workspaceScreen = $('[data-screen="workspace"]')
const uploadModal = $('[data-upload-modal]')
const confirmModal = $('[data-confirm-modal]')
const accountMenu = $('[data-account-menu]')
const accountButton = $('[data-action="toggle-account"]')
const historySearch = $('[data-history-search]')
const historySearchInput = $('[data-history-search-input]')
const documentSearch = $('[data-document-search]')
const fileInput = $('[data-file-input]')
const dropZone = $('.drop-zone')
const selectedFile = $('[data-selected-file]')
const startUploadButton = $('[data-action="start-upload"]')

function clearUploadTimers() {
  state.uploadTimers.forEach(window.clearTimeout)
  state.uploadTimers = []
}

function setRole(role) {
  state.role = role
  const user = users[role]
  workspaceScreen.dataset.role = role

  $$('[data-user-name]').forEach(node => { node.textContent = user.name })
  $$('[data-user-avatar]').forEach(node => { node.textContent = user.avatar })
  $$('[data-user-role]').forEach(node => { node.textContent = user.role })
  $$('[data-user-email]').forEach(node => { node.textContent = user.email })

  closeHistoryMenus()
  historySearchInput.value = ''
  applyHistoryFilter()
  resetConversation()

  if (role === 'member' && state.view === 'knowledge') {
    showView('chat')
  }
}

function showScreen(screen) {
  const isLogin = screen === 'login'
  loginScreen.hidden = !isLogin
  workspaceScreen.hidden = isLogin
  if (isLogin) closeAccountMenu()
}

function showView(view) {
  if (view === 'knowledge' && state.role !== 'maintainer') return

  state.view = view
  $$('[data-view]').forEach(node => {
    node.hidden = node.dataset.view !== view
  })
  $$('[data-nav]').forEach(button => {
    button.classList.toggle('is-active', button.dataset.nav === view)
  })

  $('[data-view-title]').textContent = view === 'knowledge' ? '知识库管理' : '问答'
  if (view === 'knowledge') {
    $('[data-current-conversation]').textContent = '企业共享知识库'
    $('[data-action="new-chat"]').classList.remove('is-active')
    $$('[data-history-item]').forEach(item => item.classList.remove('is-active'))
  } else if (state.currentConversation) {
    $('[data-current-conversation]').textContent = state.currentConversation.querySelector('.history-open').textContent
  } else {
    $('[data-current-conversation]').textContent = '新对话'
    $('[data-action="new-chat"]').classList.add('is-active')
  }
}

function setActiveScene(scene) {
  $$('[data-scene]').forEach(button => {
    button.classList.toggle('is-active', button.dataset.scene === scene)
  })
}

function showScene(scene) {
  closeUpload()
  setActiveScene(scene)

  if (scene === 'login') {
    showScreen('login')
    return
  }

  showScreen('workspace')

  if (scene === 'member') {
    setRole('member')
    showView('chat')
    return
  }

  setRole('maintainer')

  if (scene === 'maintainer') {
    showView('chat')
    return
  }

  showView('knowledge')

  if (scene === 'upload') {
    openUpload({ demoFile: true })
  }
}

function closeAccountMenu() {
  accountMenu.hidden = true
  accountButton.setAttribute('aria-expanded', 'false')
}

function toggleAccountMenu() {
  const willOpen = accountMenu.hidden
  accountMenu.hidden = !willOpen
  accountButton.setAttribute('aria-expanded', String(willOpen))
}

function closeHistoryMenus(exceptItem = null) {
  $$('[data-history-item]').forEach(item => {
    if (item === exceptItem) return
    const menu = item.querySelector('.history-menu')
    const trigger = item.querySelector('[data-action="toggle-history-menu"]')
    menu.hidden = true
    trigger.setAttribute('aria-expanded', 'false')
  })
}

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed
  workspaceScreen.classList.toggle('is-sidebar-collapsed', state.sidebarCollapsed)
  const button = $('[data-action="toggle-sidebar"]')
  button.setAttribute('aria-expanded', String(!state.sidebarCollapsed))
  button.setAttribute('aria-label', state.sidebarCollapsed ? '展开对话侧栏' : '收起对话侧栏')
}

function toggleHistorySearch() {
  const willOpen = historySearch.hidden
  historySearch.hidden = !willOpen
  $('[data-action="toggle-history-search"]').setAttribute('aria-expanded', String(willOpen))
  if (willOpen) historySearchInput.focus()
  if (!willOpen) {
    historySearchInput.value = ''
    applyHistoryFilter()
  }
}

function applyHistoryFilter() {
  const query = historySearchInput.value.trim().toLowerCase()
  const roleHistory = $(`.${state.role}-history`)
  let visibleCount = 0

  roleHistory.querySelectorAll('[data-history-item]').forEach(item => {
    const visible = !query || item.dataset.search.toLowerCase().includes(query)
    item.hidden = !visible
    if (visible) visibleCount += 1
  })

  $('[data-history-empty]').hidden = visibleCount !== 0
}

function finishInlineRename(item, shouldSave) {
  const input = item?.querySelector('.history-rename-input')
  if (!input) return

  const openButton = item.querySelector('.history-open')
  const nextTitle = input.value.trim()
  if (shouldSave && nextTitle) {
    openButton.textContent = nextTitle
    item.dataset.search = nextTitle.toLowerCase()
    if (state.currentConversation === item) $('[data-current-conversation]').textContent = nextTitle
  }

  input.remove()
  openButton.hidden = false
  item.classList.remove('is-renaming')
}

function startInlineRename(item) {
  if (!item || item.querySelector('.history-rename-input')) return

  const openButton = item.querySelector('.history-open')
  const input = document.createElement('input')
  input.className = 'history-rename-input'
  input.type = 'text'
  input.value = openButton.textContent
  input.setAttribute('aria-label', '重命名对话')

  openButton.hidden = true
  item.classList.add('is-renaming')
  item.insertBefore(input, item.querySelector('.history-more'))
  closeHistoryMenus()

  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault()
      finishInlineRename(item, true)
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      finishInlineRename(item, false)
    }
  })
  input.addEventListener('blur', () => finishInlineRename(item, true), { once: true })

  input.focus()
  input.select()
}

function openDeleteConfirmation(kind, target, name) {
  state.pendingDeletion = { kind, target, name }
  $('[data-confirm-title]').textContent = kind === 'history' ? '删除对话？' : '删除知识文档？'
  $('[data-confirm-message]').textContent = kind === 'history'
    ? `这会删除“${name}”。`
    : `这会删除${name}。`
  confirmModal.hidden = false
  document.body.classList.add('modal-open')
  $('[data-action="confirm-delete"]').focus()
}

function closeDeleteConfirmation() {
  if (confirmModal.hidden) return
  confirmModal.hidden = true
  state.pendingDeletion = null
  document.body.classList.remove('modal-open')
}

function confirmDeletion() {
  const pending = state.pendingDeletion
  if (!pending) return

  if (pending.kind === 'history') {
    const wasCurrent = state.currentConversation === pending.target
    pending.target.remove()
    if (wasCurrent) resetConversation()
    applyHistoryFilter()
    showToast('对话已删除')
  } else {
    pending.target.remove()
    applyDocumentFilters()
    showToast('知识文档已删除')
  }

  closeDeleteConfirmation()
}

function conversationTitle(question) {
  const compact = question.trim().replace(/[？?。！!]$/, '')
  return compact.length > 15 ? `${compact.slice(0, 15)}…` : compact
}

function createHistoryItem(question) {
  const item = document.createElement('article')
  const openButton = document.createElement('button')
  const moreButton = document.createElement('button')
  const menu = document.createElement('div')
  const renameButton = document.createElement('button')
  const deleteButton = document.createElement('button')
  const title = conversationTitle(question)

  item.className = 'history-item is-active'
  item.dataset.historyItem = ''
  item.dataset.search = title.toLowerCase()

  openButton.className = 'history-open'
  openButton.type = 'button'
  openButton.dataset.historyQuestion = question
  openButton.textContent = title

  moreButton.className = 'history-more'
  moreButton.type = 'button'
  moreButton.dataset.action = 'toggle-history-menu'
  moreButton.setAttribute('aria-label', '管理对话')
  moreButton.setAttribute('aria-expanded', 'false')
  moreButton.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="4" cy="10" r="1"></circle><circle cx="10" cy="10" r="1"></circle><circle cx="16" cy="10" r="1"></circle></svg>'

  menu.className = 'history-menu'
  menu.hidden = true
  renameButton.type = 'button'
  renameButton.dataset.action = 'rename-history'
  renameButton.textContent = '重命名'
  deleteButton.className = 'danger'
  deleteButton.type = 'button'
  deleteButton.dataset.action = 'delete-history'
  deleteButton.textContent = '删除'
  menu.append(renameButton, deleteButton)
  item.append(openButton, moreButton, menu)

  $(`.${state.role}-history`).prepend(item)
  return item
}

function selectHistoryItem(item) {
  state.currentConversation = item
  $$('[data-history-item]').forEach(historyItem => historyItem.classList.toggle('is-active', historyItem === item))
  $('[data-action="new-chat"]').classList.remove('is-active')
  showView('chat')
  showConversation(item.querySelector('.history-open').dataset.historyQuestion, { createHistory: false })
  closeHistoryMenus()
}

function showConversation(question, options = {}) {
  const emptyState = $('[data-chat-empty]')
  const conversation = $('[data-conversation]')
  const userMessage = $('.user-message')

  if (question.trim()) userMessage.textContent = question.trim()
  if (!state.currentConversation && options.createHistory !== false) {
    state.currentConversation = createHistoryItem(question)
  }
  if (state.currentConversation) {
    $('[data-current-conversation]').textContent = state.currentConversation.querySelector('.history-open').textContent
    $('[data-action="new-chat"]').classList.remove('is-active')
  }
  emptyState.hidden = true
  conversation.hidden = false
}

function resetConversation() {
  state.currentConversation = null
  $('[data-chat-empty]').hidden = false
  $('[data-conversation]').hidden = true
  $('[data-chat-input]').value = ''
  $('[data-current-conversation]').textContent = '新对话'
  $$('[data-history-item]').forEach(item => item.classList.remove('is-active'))
  $('[data-action="new-chat"]').classList.add('is-active')
}

function applyDocumentFilters() {
  const query = documentSearch.value.trim().toLowerCase()
  let visibleCount = 0

  $$('[data-document-row]').forEach(row => {
    const matchesStatus = state.statusFilter === 'all' || row.dataset.status === state.statusFilter
    const matchesQuery = !query || row.dataset.search.toLowerCase().includes(query)
    const visible = matchesStatus && matchesQuery
    row.hidden = !visible
    if (visible) visibleCount += 1
  })

  $('[data-document-list]').hidden = visibleCount === 0
  $('[data-document-empty]').hidden = visibleCount !== 0
}

function setStatusFilter(filter) {
  state.statusFilter = filter
  $$('[data-status-filter]').forEach(button => {
    button.classList.toggle('is-active', button.dataset.statusFilter === filter)
  })
  applyDocumentFilters()
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '演示文件'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function extensionLabel(filename) {
  const extension = filename.split('.').pop()?.toUpperCase() || 'FILE'
  if (extension === 'DOCX') return 'DOC'
  if (extension === 'XLSX') return 'XLS'
  return extension.slice(0, 4)
}

function extensionClass(filename) {
  const extension = filename.split('.').pop()?.toLowerCase()
  if (extension === 'pdf') return 'file-icon-pdf'
  if (extension === 'xls' || extension === 'xlsx') return 'file-icon-xls'
  return 'file-icon-doc'
}

function displaySelectedFile(file) {
  state.selectedFile = file
  const name = file.name
  const extensionNode = $('[data-selected-extension]')

  $('[data-selected-name]').textContent = name
  $('[data-selected-size]').textContent = formatBytes(file.size)
  extensionNode.textContent = extensionLabel(name)
  extensionNode.className = `file-icon ${extensionClass(name)}`

  dropZone.hidden = true
  selectedFile.hidden = false
  startUploadButton.disabled = false
}

function clearSelectedFile() {
  state.selectedFile = null
  fileInput.value = ''
  selectedFile.hidden = true
  dropZone.hidden = false
  startUploadButton.disabled = true
}

function setDemoFile() {
  displaySelectedFile({
    name: '监管数据质量管理办法.pdf',
    size: 2.4 * 1024 * 1024,
  })
}

function resetUploadDialog() {
  clearUploadTimers()
  $('[data-upload-step="select"]').hidden = false
  $('[data-upload-step="progress"]').hidden = true
  $('[data-upload-footer]').hidden = false
  $('[data-progress-percent]').textContent = '0%'
  $('[data-progress-bar]').style.width = '0%'
  clearSelectedFile()
}

function openUpload(options = {}) {
  resetUploadDialog()
  uploadModal.hidden = false
  document.body.classList.add('modal-open')

  if (options.demoFile) setDemoFile()
  if (options.progress) {
    setDemoFile()
    startUpload(options.progress)
  }
}

function closeUpload() {
  if (uploadModal.hidden) return
  clearUploadTimers()
  uploadModal.hidden = true
  document.body.classList.remove('modal-open')
}

function setProgress(percent, stageIndex) {
  $('[data-progress-percent]').textContent = `${percent}%`
  $('[data-progress-bar]').style.width = `${percent}%`

  const steps = $$('.ingestion-steps li')
  steps.forEach((step, index) => {
    step.classList.toggle('is-complete', index < stageIndex)
    step.classList.toggle('is-active', index === stageIndex)

    const icon = step.querySelector('i')
    icon.innerHTML = index < stageIndex
      ? '<svg viewBox="0 0 20 20"><path d="m5 10 3 3 7-7"></path></svg>'
      : ''
  })
}

function startUpload(initialPercent = 24) {
  if (!state.selectedFile) return

  const filename = state.selectedFile.name
  $('[data-progress-name]').textContent = filename
  $('[data-upload-step="select"]').hidden = true
  $('[data-upload-step="progress"]').hidden = false
  $('[data-upload-footer]').hidden = true

  setProgress(initialPercent, initialPercent >= 60 ? 2 : 1)

  const milestones = initialPercent >= 60
    ? [[88, 2, 900], [100, 3, 1900]]
    : [[58, 1, 800], [78, 2, 1650], [94, 2, 2450], [100, 3, 3250]]

  milestones.forEach(([percent, stage, delay]) => {
    state.uploadTimers.push(window.setTimeout(() => {
      setProgress(percent, stage)
      if (percent === 100) completeUpload()
    }, delay))
  })
}

function completeUpload() {
  const steps = $$('.ingestion-steps li')
  steps.forEach(step => {
    step.classList.remove('is-active')
    step.classList.add('is-complete')
    step.querySelector('i').innerHTML = '<svg viewBox="0 0 20 20"><path d="m5 10 3 3 7-7"></path></svg>'
  })

  state.uploadTimers.push(window.setTimeout(() => {
    closeUpload()
    showToast('新文档已入库并可以参与问答')
    setActiveScene('knowledge')
  }, 900))
}

function showToast(message) {
  const toast = $('[data-toast]')
  $('[data-toast-text]').textContent = message
  toast.hidden = false
  window.setTimeout(() => { toast.hidden = true }, 2600)
}

document.addEventListener('click', event => {
  const actionButton = event.target.closest('[data-action]')
  const navButton = event.target.closest('[data-nav]')
  const sceneButton = event.target.closest('[data-scene]')
  const suggestion = event.target.closest('[data-suggestion]')
  const filterButton = event.target.closest('[data-status-filter]')
  const historyOpen = event.target.closest('.history-open')

  if (sceneButton) {
    showScene(sceneButton.dataset.scene)
    return
  }

  if (navButton) {
    showView(navButton.dataset.nav)
    if (navButton.dataset.nav === 'chat') {
      setActiveScene(state.role === 'maintainer' ? 'maintainer' : 'member')
    } else {
      setActiveScene('knowledge')
    }
    closeAccountMenu()
    return
  }

  if (suggestion) {
    const question = suggestion.dataset.suggestion
    $('[data-chat-input]').value = question
    showConversation(question)
    return
  }

  if (filterButton) {
    setStatusFilter(filterButton.dataset.statusFilter)
    return
  }

  if (historyOpen) {
    selectHistoryItem(historyOpen.closest('[data-history-item]'))
    setActiveScene(state.role === 'maintainer' ? 'maintainer' : 'member')
    return
  }

  if (!actionButton) {
    if (!event.target.closest('.account-area')) closeAccountMenu()
    if (!event.target.closest('[data-history-item]')) closeHistoryMenus()
    return
  }

  const action = actionButton.dataset.action

  if (action === 'login') showScene('member')
  if (action === 'logout') showScene('login')
  if (action === 'toggle-account') toggleAccountMenu()
  if (action === 'toggle-sidebar') toggleSidebar()
  if (action === 'toggle-history-search') toggleHistorySearch()
  if (action === 'new-chat') {
    showView('chat')
    resetConversation()
    setActiveScene(state.role === 'maintainer' ? 'maintainer' : 'member')
  }
  if (action === 'open-upload') openUpload()
  if (action === 'close-upload') closeUpload()
  if (action === 'choose-file') fileInput.click()
  if (action === 'clear-file') clearSelectedFile()
  if (action === 'start-upload') startUpload()

  if (action === 'toggle-history-menu') {
    const item = actionButton.closest('[data-history-item]')
    const menu = item.querySelector('.history-menu')
    const willOpen = menu.hidden
    closeHistoryMenus(item)
    menu.hidden = !willOpen
    actionButton.setAttribute('aria-expanded', String(willOpen))
  }

  if (action === 'rename-history') {
    const item = actionButton.closest('[data-history-item]')
    startInlineRename(item)
  }

  if (action === 'delete-history') {
    const item = actionButton.closest('[data-history-item]')
    const title = item.querySelector('.history-open').textContent
    closeHistoryMenus()
    openDeleteConfirmation('history', item, title)
  }

  if (action === 'show-detail' || action === 'delete-document') {
    const documentName = actionButton
      .closest('[data-document-row]')
      ?.querySelector('.document-primary strong')
      ?.textContent

    if (action === 'show-detail') showToast(`查看${documentName}详情`)
    if (action === 'delete-document') {
      openDeleteConfirmation('document', actionButton.closest('[data-document-row]'), documentName)
    }
  }

  if (action === 'cancel-delete') closeDeleteConfirmation()
  if (action === 'confirm-delete') confirmDeletion()

  if (action === 'toggle-evidence') {
    const evidenceList = $('[data-evidence-list]')
    evidenceList.hidden = !evidenceList.hidden
    actionButton.classList.toggle('is-open', !evidenceList.hidden)
  }
})

$('[data-chat-form]').addEventListener('submit', event => {
  event.preventDefault()
  const input = $('[data-chat-input]')
  if (!input.value.trim()) return
  showConversation(input.value)
})

$('[data-chat-input]').addEventListener('input', event => {
  event.target.style.height = 'auto'
  event.target.style.height = `${Math.min(event.target.scrollHeight, 110)}px`
})

documentSearch.addEventListener('input', applyDocumentFilters)
historySearchInput.addEventListener('input', applyHistoryFilter)

fileInput.addEventListener('change', () => {
  const [file] = fileInput.files
  if (file) displaySelectedFile(file)
})

;['dragenter', 'dragover'].forEach(type => {
  dropZone.addEventListener(type, event => {
    event.preventDefault()
    dropZone.classList.add('is-dragover')
  })
})

;['dragleave', 'drop'].forEach(type => {
  dropZone.addEventListener(type, event => {
    event.preventDefault()
    dropZone.classList.remove('is-dragover')
  })
})

dropZone.addEventListener('drop', event => {
  const [file] = event.dataTransfer.files
  if (file) displaySelectedFile(file)
})

uploadModal.addEventListener('click', event => {
  if (event.target === uploadModal) closeUpload()
})

confirmModal.addEventListener('click', event => {
  if (event.target === confirmModal) closeDeleteConfirmation()
})

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    closeUpload()
    closeDeleteConfirmation()
    closeAccountMenu()
    closeHistoryMenus()
  }
})

setRole('member')
showScreen('login')
showView('chat')

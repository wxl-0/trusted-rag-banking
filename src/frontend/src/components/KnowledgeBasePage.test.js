import assert from 'node:assert/strict'
import test from 'node:test'

import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'


async function loadComponent(path) {
  const server = await createServer({
    appType: 'custom',
    server: { middlewareMode: true },
  })
  try {
    return (await server.ssrLoadModule(path)).default
  } finally {
    await server.close()
  }
}

test('knowledge page keeps the approved document list format', async () => {
  const KnowledgeBasePage = await loadComponent('/src/components/KnowledgeBasePage.jsx')
  const html = renderToStaticMarkup(React.createElement(KnowledgeBasePage, {
    summary: { succeeded: 1, in_progress: 2, failed: 3, updated_at: '2026-08-29T10:32:00Z' },
    documents: [{
      id: 'document-1',
      sequence: 1,
      filename: '商业银行资本管理办法.docx',
      size_bytes: 3355443,
      status: 'in_progress',
      updated_at: '2026-08-29T09:35:00Z',
    }],
    detail: null,
    loading: false,
    error: '',
    status: '',
    nextCursor: null,
    onSearch: () => {},
    onStatusChange: () => {},
    onShowDetail: () => {},
    onCloseDetail: () => {},
    onNextPage: () => {},
  }))

  for (const label of ['企业共享知识库', '知识文档', '序号', '文件名', '大小', '入库状态', '更新时间', '操作']) {
    assert.match(html, new RegExp(label))
  }
  assert.match(html, /《商业银行资本管理办法\.docx》/)
  assert.match(html, /进行中/)
  assert.doesNotMatch(html, /上传知识文档|删除|文件类型|发布机构/)
})

test('only a knowledge maintainer receives the knowledge navigation entry', async () => {
  const ConversationSidebar = await loadComponent('/src/components/ConversationSidebar.jsx')
  const props = {
    conversations: [],
    currentId: null,
    collapsed: false,
    activeView: 'chat',
    onNew: () => {},
    onSelect: () => {},
    onSearch: () => {},
    onRename: () => {},
    onDelete: () => {},
    onShowKnowledgeBase: () => {},
  }
  const memberHtml = renderToStaticMarkup(React.createElement(
    ConversationSidebar, { ...props, showKnowledgeBase: false },
  ))
  const maintainerHtml = renderToStaticMarkup(React.createElement(
    ConversationSidebar, { ...props, showKnowledgeBase: true },
  ))

  assert.doesNotMatch(memberHtml, /知识库管理/)
  assert.match(maintainerHtml, /知识库管理/)
})

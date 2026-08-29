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
    onRequestDelete: () => {},
    onCloseDetail: () => {},
    onNextPage: () => {},
  }))

  for (const label of ['企业共享知识库', '知识文档', '序号', '文件名', '大小', '入库状态', '更新时间', '操作']) {
    assert.match(html, new RegExp(label))
  }
  assert.match(html, /《商业银行资本管理办法\.docx》/)
  assert.match(html, /进行中/)
  assert.match(html, /删除/)
  assert.doesNotMatch(html, /文件类型|发布机构/)
})

test('knowledge page renders the approved deletion confirmation without extra copy', async () => {
  const KnowledgeBasePage = await loadComponent('/src/components/KnowledgeBasePage.jsx')
  const html = renderToStaticMarkup(React.createElement(KnowledgeBasePage, {
    summary: null,
    documents: [],
    detail: null,
    deleteTarget: { id: 'document-1' },
    deleteLoading: false,
    loading: false,
    error: '',
    search: '',
    status: '',
    onSearch: () => {},
    onStatusChange: () => {},
    onShowDetail: () => {},
    onRequestDelete: () => {},
    onCancelDelete: () => {},
    onConfirmDelete: () => {},
    onCloseDetail: () => {},
    onPageChange: () => {},
  }))

  assert.match(html, /role="dialog"/)
  assert.match(html, /删除知识文档？/)
  assert.match(html, />取消</)
  assert.match(html, />删除</)
  const dialog = html.match(/<section class="confirm-dialog knowledge-delete-dialog"[\s\S]*?<\/section>/)?.[0] || ''
  assert.doesNotMatch(dialog, /这会删除|删除后|无法恢复|文档名称/)
})

test('knowledge page renders an empty multi-file drop zone', async () => {
  const KnowledgeBasePage = await loadComponent('/src/components/KnowledgeBasePage.jsx')
  const html = renderToStaticMarkup(React.createElement(KnowledgeBasePage, {
    summary: null,
    documents: [],
    detail: null,
    loading: false,
    error: '',
    search: '',
    status: '',
    nextCursor: null,
    uploadOpen: true,
    uploadItems: [],
    uploadLoading: false,
    uploadStarted: false,
    uploadError: '',
    onSearch: () => {},
    onStatusChange: () => {},
    onShowDetail: () => {},
    onCloseDetail: () => {},
    onNextPage: () => {},
    onOpenUpload: () => {},
    onCloseUpload: () => {},
    onAddUploadFiles: () => {},
    onRemoveUploadFile: () => {},
    onSubmitUpload: () => {},
  }))

  assert.match(html, /上传知识文档/)
  assert.match(html, /拖放文件到这里，或点击选择/)
  assert.match(html, /multiple=""/)
  assert.match(html, /单个文件不超过 50 MiB/)
  assert.match(html, /开始上传/)
  assert.match(html, /disabled=""/)
})

test('knowledge page renders the compact batch queue and per-file states', async () => {
  const KnowledgeBasePage = await loadComponent('/src/components/KnowledgeBasePage.jsx')
  const html = renderToStaticMarkup(React.createElement(KnowledgeBasePage, {
    summary: null,
    documents: [],
    detail: null,
    loading: false,
    error: '',
    search: '',
    status: '',
    uploadOpen: true,
    uploadItems: [
      {
        id: 'ready-file',
        file: { name: '监管数据质量管理办法.pdf', size: 2516582 },
        status: 'ready',
        message: '',
      },
      {
        id: 'invalid-file',
        file: { name: '监管数据质量管理办法.txt', size: 1024 },
        status: 'validation_failed',
        message: '仅支持 DOC、DOCX、PDF、XLS 和 XLSX 文件',
      },
    ],
    uploadLoading: false,
    uploadStarted: false,
    uploadError: '单批最多选择 10 个文件，超出的 1 个文件未添加',
    onSearch: () => {},
    onStatusChange: () => {},
    onShowDetail: () => {},
    onCloseDetail: () => {},
    onOpenUpload: () => {},
    onCloseUpload: () => {},
    onAddUploadFiles: () => {},
    onRemoveUploadFile: () => {},
    onSubmitUpload: () => {},
  }))

  assert.match(html, /继续添加文件/)
  assert.match(html, /监管数据质量管理办法\.pdf/)
  assert.match(html, /待上传/)
  assert.match(html, /校验失败/)
  assert.match(html, /已选 2 个文件/)
  assert.match(html, /开始上传/)
  assert.match(html, /单批最多选择 10 个文件，超出的 1 个文件未添加/)
  assert.match(html, /仅支持 DOC、DOCX、PDF、XLS 和 XLSX 文件/)
  assert.doesNotMatch(html, /解析与切块|建立检索索引|启用新版本|开始入库/)
})

test('knowledge page renders ten-item numbered pagination', async () => {
  const KnowledgeBasePage = await loadComponent('/src/components/KnowledgeBasePage.jsx')
  const html = renderToStaticMarkup(React.createElement(KnowledgeBasePage, {
    summary: null,
    documents: [],
    detail: null,
    loading: false,
    error: '',
    search: '',
    status: '',
    page: 10,
    pageSize: 10,
    total: 200,
    onSearch: () => {},
    onStatusChange: () => {},
    onShowDetail: () => {},
    onCloseDetail: () => {},
    onPageChange: () => {},
  }))

  assert.match(html, /上一页/)
  assert.match(html, /下一页/)
  assert.match(html, /aria-current="page">10/)
  for (const page of [1, 9, 11, 20]) assert.match(html, new RegExp(`>${page}<`))
  assert.match(html, /…/)
  assert.match(html, /共 200 篇/)
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

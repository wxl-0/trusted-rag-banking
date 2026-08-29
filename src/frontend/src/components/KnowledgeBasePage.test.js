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
    loading: false,
    error: '',
    status: '',
    nextCursor: null,
    onSearch: () => {},
    onStatusChange: () => {},
    onDownload: () => {},
    onRequestDelete: () => {},
    onNextPage: () => {},
  }))

  for (const label of ['企业共享知识库', '知识文档', '序号', '文件名', '大小', '入库状态', '更新时间', '操作']) {
    assert.match(html, new RegExp(label))
  }
  assert.match(html, /《商业银行资本管理办法\.docx》/)
  assert.match(html, /data-full-name="《商业银行资本管理办法\.docx》"/)
  assert.doesNotMatch(html, /title="《商业银行资本管理办法\.docx》"/)
  assert.match(html, /进行中/)
  assert.match(html, /下载/)
  assert.match(html, /删除/)
  assert.doesNotMatch(html, /详情|文件类型|发布机构/)
})

test('knowledge update times show the time today and month-day otherwise', async () => {
  const KnowledgeBasePage = await loadComponent('/src/components/KnowledgeBasePage.jsx')
  const today = new Date()
  today.setHours(17, 38, 0, 0)
  const previousDay = new Date(today)
  previousDay.setDate(previousDay.getDate() - 1)
  const previousDayLabel = `${previousDay.getMonth() + 1}月${previousDay.getDate()}日`
  const html = renderToStaticMarkup(React.createElement(KnowledgeBasePage, {
    summary: { succeeded: 1, in_progress: 0, failed: 0, updated_at: today.toISOString() },
    documents: [{
      id: 'document-1',
      sequence: 1,
      filename: '监管文件.pdf',
      size_bytes: 1024,
      status: 'succeeded',
      updated_at: previousDay.toISOString(),
    }],
    loading: false,
    error: '',
    search: '',
    status: '',
    onSearch: () => {},
    onStatusChange: () => {},
    onDownload: () => {},
    onRequestDelete: () => {},
    onPageChange: () => {},
  }))

  assert.match(html, /最近更新：17:38/)
  assert.match(html, new RegExp(previousDayLabel))
})

test('knowledge page renders the document name in the shared deletion confirmation', async () => {
  const KnowledgeBasePage = await loadComponent('/src/components/KnowledgeBasePage.jsx')
  const html = renderToStaticMarkup(React.createElement(KnowledgeBasePage, {
    summary: null,
    documents: [],
    deleteTarget: { id: 'document-1', filename: '商业银行资本管理办法.docx' },
    deleteLoading: false,
    loading: false,
    error: '',
    search: '',
    status: '',
    onSearch: () => {},
    onStatusChange: () => {},
    onDownload: () => {},
    onRequestDelete: () => {},
    onCancelDelete: () => {},
    onConfirmDelete: () => {},
    onPageChange: () => {},
  }))

  assert.match(html, /role="dialog"/)
  assert.match(html, /删除知识文档？/)
  assert.match(html, /这会删除《<strong>商业银行资本管理办法\.docx<\/strong>》/)
  assert.match(html, />取消</)
  assert.match(html, />删除</)
  const dialog = html.match(/<section class="confirm-dialog"[\s\S]*?<\/section>/)?.[0] || ''
  assert.doesNotMatch(dialog, /删除后|无法恢复|文档名称/)
})

test('shared deletion confirmation only bolds the target name', async () => {
  const DeleteConfirmDialog = await loadComponent('/src/components/DeleteConfirmDialog.jsx')
  const html = renderToStaticMarkup(React.createElement(DeleteConfirmDialog, {
    title: '删除对话？',
    beforeName: '这会删除“',
    name: '资本管理问答',
    afterName: '”',
    onCancel: () => {},
    onConfirm: () => {},
  }))

  assert.match(html, /<h2[^>]*>删除对话？<\/h2>/)
  assert.match(html, /这会删除“<strong>资本管理问答<\/strong>”/)
  assert.equal((html.match(/<strong>/g) || []).length, 1)
})

test('knowledge page renders an empty multi-file drop zone', async () => {
  const KnowledgeBasePage = await loadComponent('/src/components/KnowledgeBasePage.jsx')
  const html = renderToStaticMarkup(React.createElement(KnowledgeBasePage, {
    summary: null,
    documents: [],
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
    onDownload: () => {},
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
    onDownload: () => {},
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
    loading: false,
    error: '',
    search: '',
    status: '',
    page: 10,
    pageSize: 10,
    total: 200,
    onSearch: () => {},
    onStatusChange: () => {},
    onDownload: () => {},
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

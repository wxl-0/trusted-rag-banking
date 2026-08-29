import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MAX_UPLOAD_FILE_BYTES,
  runWithConcurrency,
  validateUploadItems,
} from './uploadBatch.js'


function item(id, name, size = 1024) {
  return { id, file: { name, size }, status: 'ready', message: '' }
}

test('batch validation rejects unsupported, oversized, and duplicate files independently', () => {
  const validated = validateUploadItems([
    item('first', '监管办法.PDF'),
    item('duplicate', '监管办法.pdf'),
    item('unsupported', '说明.txt'),
    item('oversized', '报表.xlsx', MAX_UPLOAD_FILE_BYTES + 1),
    item('ready', '资本管理办法.docx'),
  ])

  assert.deepEqual(validated.map(entry => entry.status), [
    'validation_failed',
    'validation_failed',
    'validation_failed',
    'validation_failed',
    'ready',
  ])
  assert.equal(validated[0].message, '同一批次中存在重名文件')
  assert.equal(validated[2].message, '仅支持 DOC、DOCX、PDF、XLS 和 XLSX 文件')
  assert.equal(validated[3].message, '单个文件不能超过 50 MiB')
})

test('batch runner never exceeds the fixed concurrency', async () => {
  let active = 0
  let maximumActive = 0
  const completed = []

  await runWithConcurrency([1, 2, 3, 4, 5, 6, 7], 3, async value => {
    active += 1
    maximumActive = Math.max(maximumActive, active)
    await new Promise(resolve => setTimeout(resolve, 5))
    completed.push(value)
    active -= 1
  })

  assert.equal(maximumActive, 3)
  assert.deepEqual(completed.sort((left, right) => left - right), [1, 2, 3, 4, 5, 6, 7])
})

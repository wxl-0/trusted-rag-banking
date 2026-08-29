export const MAX_UPLOAD_FILES = 10
export const MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024
export const MAX_UPLOAD_BATCH_BYTES = 200 * 1024 * 1024
export const UPLOAD_CONCURRENCY = 3

const SUPPORTED_EXTENSIONS = new Set(['doc', 'docx', 'pdf', 'xls', 'xlsx'])

function normalizedName(name) {
  return name.trim().toLowerCase()
}

export function createUploadItems(files) {
  return Array.from(files).map((file, index) => ({
    id: globalThis.crypto?.randomUUID?.()
      || `${Date.now()}-${index}-${Math.random()}`,
    file,
    status: 'ready',
    message: '',
  }))
}

export function validateUploadItems(items) {
  const nameCounts = new Map()
  for (const item of items) {
    const name = normalizedName(item.file.name)
    nameCounts.set(name, (nameCounts.get(name) || 0) + 1)
  }

  return items.map(item => {
    const extension = item.file.name.split('.').pop()?.toLowerCase() || ''
    let message = ''
    if (!SUPPORTED_EXTENSIONS.has(extension)) {
      message = '仅支持 DOC、DOCX、PDF、XLS 和 XLSX 文件'
    } else if (item.file.size > MAX_UPLOAD_FILE_BYTES) {
      message = '单个文件不能超过 50 MiB'
    } else if (nameCounts.get(normalizedName(item.file.name)) > 1) {
      message = '同一批次中存在重名文件'
    }
    return {
      ...item,
      status: message ? 'validation_failed' : 'ready',
      message,
    }
  })
}

export async function runWithConcurrency(items, limit, worker) {
  let nextIndex = 0
  const runners = Array.from(
    { length: Math.min(limit, items.length) },
    async () => {
      while (nextIndex < items.length) {
        const item = items[nextIndex]
        nextIndex += 1
        await worker(item)
      }
    },
  )
  await Promise.all(runners)
}

export function isUploadValidationError(error) {
  return [409, 413, 422].includes(error?.status)
}

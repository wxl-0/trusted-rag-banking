import assert from 'node:assert/strict'
import test from 'node:test'

import { focusableElements, keepFocusInDialog } from './dialogFocus.js'


function element({ hidden = false } = {}) {
  return {
    focused: false,
    focus() { this.focused = true },
    getAttribute(name) {
      return name === 'aria-hidden' && hidden ? 'true' : null
    },
  }
}


test('dialog focus helpers exclude aria-hidden controls', () => {
  const visible = element()
  const hidden = element({ hidden: true })
  const container = { querySelectorAll: () => [visible, hidden] }

  assert.deepEqual(focusableElements(container), [visible])
})


test('Tab and Shift+Tab cycle inside the dialog', () => {
  const first = element()
  const last = element()
  const container = { querySelectorAll: () => [first, last] }
  const originalDocument = globalThis.document

  try {
    globalThis.document = { activeElement: last }
    let prevented = false
    keepFocusInDialog({
      key: 'Tab',
      shiftKey: false,
      preventDefault: () => { prevented = true },
    }, container)
    assert.equal(prevented, true)
    assert.equal(first.focused, true)

    globalThis.document.activeElement = first
    prevented = false
    keepFocusInDialog({
      key: 'Tab',
      shiftKey: true,
      preventDefault: () => { prevented = true },
    }, container)
    assert.equal(prevented, true)
    assert.equal(last.focused, true)
  } finally {
    globalThis.document = originalDocument
  }
})

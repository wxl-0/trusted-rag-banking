import { useEffect, useRef } from 'react'


const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')


export function focusableElements(container) {
  if (!container) return []
  return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR))
    .filter(element => element.getAttribute('aria-hidden') !== 'true')
}


export function keepFocusInDialog(event, container) {
  if (event.key !== 'Tab') return
  const elements = focusableElements(container)
  if (!elements.length) {
    event.preventDefault()
    container?.focus()
    return
  }

  const first = elements[0]
  const last = elements[elements.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}


export function useDialogFocus() {
  const dialogRef = useRef(null)

  useEffect(() => {
    const previousFocus = document.activeElement
    const dialog = dialogRef.current
    const initialTarget = focusableElements(dialog)[0] || dialog
    initialTarget?.focus()

    return () => {
      if (previousFocus && typeof previousFocus.focus === 'function') {
        previousFocus.focus()
      }
    }
  }, [])

  return dialogRef
}

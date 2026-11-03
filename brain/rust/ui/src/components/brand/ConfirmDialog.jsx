import { useEffect, useId, useRef, useState } from 'react'
import { friendlyError } from '../../lib/instances'
import { Button } from './primitives'
import styles from './ConfirmDialog.module.css'

/**
 * Ask before acting. `onConfirm` may be async: the dialog stays open while it
 * runs and shows its error if it fails. Cancel has focus first (the safe choice).
 * `danger` marks the confirm red; use it only for actions that can't be undone.
 */
export default function ConfirmDialog({ open, title, children, confirmLabel, danger = false, onConfirm, onCancel }) {
  const ref = useRef(null)
  const cancelRef = useRef(null)
  const titleId = useId()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const d = ref.current
    if (open && !d.open) {
      setError(null)
      d.showModal()
      cancelRef.current?.focus()
    } else if (!open && d.open) {
      d.close()
    }
  }, [open])

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      await onConfirm()
    } catch (e) {
      setError(friendlyError(e.message || String(e)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault() // Esc: close through state, never behind React's back
        if (!busy) onCancel()
      }}
    >
      <h2 id={titleId} className={`t-h2 ${styles.title}`}>
        {title}
      </h2>
      <div className={`t-body ${styles.body}`}>{children}</div>
      {error && (
        <p className={`t-small ${styles.error}`} role="alert">
          {error}
        </p>
      )}
      <div className={styles.actions}>
        <CancelButton innerRef={cancelRef} onClick={onCancel} disabled={busy} />
        <Button variant={danger ? 'quiet' : 'primary'} className={danger ? styles.danger : undefined} onClick={confirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </Button>
      </div>
    </dialog>
  )
}

function CancelButton({ innerRef, onClick, disabled }) {
  // Button doesn't forward refs; a plain wrapper keeps the primitive unchanged.
  return (
    <span ref={(el) => (innerRef.current = el?.querySelector('button') ?? null)}>
      <Button onClick={onClick} disabled={disabled}>
        Cancel
      </Button>
    </span>
  )
}

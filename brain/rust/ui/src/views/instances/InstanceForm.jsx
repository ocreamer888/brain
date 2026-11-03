import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/brand/primitives'
import { friendlyError, parseTagInput } from '../../lib/instances'
import dialog from '../../components/brand/ConfirmDialog.module.css'
import styles from './InstanceForm.module.css'

/**
 * Create or edit a brain, in a modal (same shell as ConfirmDialog). `instance`
 * null = create. `onSubmit(body)` may throw; its error is shown in the form.
 */
export default function InstanceForm({ open, instance, onSubmit, onClose }) {
  const ref = useRef(null)
  const ids = { title: useId(), name: useId(), desc: useId(), tags: useId(), err: useId() }
  const [fields, setFields] = useState({ name: '', description: '', tags: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const d = ref.current
    if (open && !d.open) {
      setFields({
        name: instance?.name ?? '',
        description: instance?.description ?? '',
        tags: (instance?.tags ?? []).join(', '),
      })
      setError(null)
      d.showModal()
    } else if (!open && d.open) d.close()
  }, [open, instance])

  async function submit(e) {
    e.preventDefault()
    if (!fields.name.trim()) return setError('Give the brain a name.')
    setBusy(true)
    setError(null)
    try {
      await onSubmit({ name: fields.name.trim(), description: fields.description.trim(), tags: parseTagInput(fields.tags) })
    } catch (err) {
      setError(friendlyError(err.message || String(err)))
    } finally {
      setBusy(false)
    }
  }

  const set = (k) => (e) => setFields((f) => ({ ...f, [k]: e.target.value }))
  return (
    <dialog ref={ref} className={dialog.dialog} aria-labelledby={ids.title} onCancel={(e) => (e.preventDefault(), !busy && onClose())}>
      <form onSubmit={submit} noValidate>
        <h2 id={ids.title} className={`t-h2 ${dialog.title}`}>{instance ? `Edit ${instance.name}` : 'New brain'}</h2>
        <div className={styles.fields}>
          <Field id={ids.name} label="Name" value={fields.name} onChange={set('name')} required autoFocus invalid={!!error} describedBy={error ? ids.err : undefined} />
          <Field id={ids.desc} label="Description" hint="Optional. What this brain is for." value={fields.description} onChange={set('description')} />
          <Field id={ids.tags} label="Tags" hint="Optional, comma-separated." value={fields.tags} onChange={set('tags')} />
        </div>
        {error && <p id={ids.err} className={`t-small ${dialog.error}`} role="alert">{error}</p>}
        <div className={dialog.actions}>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={busy}>
            {busy ? 'Saving…' : instance ? 'Save' : 'Create brain'}
          </Button>
        </div>
      </form>
    </dialog>
  )
}

function Field({ id, label, hint, invalid, describedBy, ...input }) {
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={`t-label ${styles.label}`}>{label}</label>
      <input id={id} className={styles.input} aria-invalid={invalid || undefined} aria-describedby={[hintId, describedBy].filter(Boolean).join(' ') || undefined} {...input} />
      {hint && <span id={hintId} className={`t-small ${styles.hint}`}>{hint}</span>}
    </div>
  )
}

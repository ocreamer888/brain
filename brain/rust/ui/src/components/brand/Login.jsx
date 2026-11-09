import { useId, useState } from 'react'
import GlowHero from './GlowHero'
import { Button } from './primitives'
import styles from './Login.module.css'

/**
 * The lock screen (brand book §6.4 names "login" as the next context for the
 * glow-hero treatment; §8.4's star field sits behind it). One Level-4 glow,
 * Split mesh: the key field and unlock button live in GlowHero's `actions`
 * slot, on the lamp, so they already follow the light scheme in both
 * appearances. Presentational only — collects the key and calls `onUnlock`.
 * No storage, no fetch, no validation here.
 */
export default function Login({ onUnlock, busy, error }) {
  const [key, setKey] = useState('')
  const ids = { key: useId(), err: useId() }
  const message = errorText(error)

  function submit(e) {
    e.preventDefault()
    const trimmed = key.trim()
    if (!trimmed || busy) return
    onUnlock(trimmed)
  }

  return (
    <div className={styles.page}>
      <div className={styles.shell}>
        <GlowHero
          label="Brain"
          value="Locked"
          caption="Enter the key to unlock this brain."
          actions={
            <form className={styles.form} onSubmit={submit} noValidate>
              <div className={styles.row}>
                <label htmlFor={ids.key} className="sr-only">Access key</label>
                <input
                  id={ids.key}
                  className={styles.input}
                  type="text"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  autoFocus
                  placeholder="Key"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  disabled={busy}
                  aria-invalid={message ? true : undefined}
                  aria-describedby={message ? ids.err : undefined}
                />
                <Button variant="primary" type="submit" disabled={busy || !key.trim()}>
                  {busy ? 'Unlocking…' : 'Unlock'}
                </Button>
              </div>
              {message && (
                <p id={ids.err} className={`t-small ${styles.error}`} role="alert">
                  {message}
                </p>
              )}
              {busy && (
                <p className={`t-small ${styles.wait}`} role="status">
                  <span className={styles.waitDot} aria-hidden />
                  Checking…
                </p>
              )}
            </form>
          }
        />
      </div>
    </div>
  )
}

/**
 * `error` arrives already in the brand's voice (AuthGate sets "Session
 * expired. Please re-enter your key.", "That key was not accepted.", or a
 * server-provided message) -- shown as-is, with a quiet fallback only if the
 * caller ever passes an empty string.
 */
function errorText(error) {
  if (!error) return null
  return String(error).trim() || "That key didn't work."
}

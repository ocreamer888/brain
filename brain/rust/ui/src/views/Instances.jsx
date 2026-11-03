import { useState } from 'react'
import {
  archiveInstance,
  createInstance,
  deleteInstance,
  listInstances,
  patchInstance,
  switchInstance,
  unarchiveInstance,
} from '../api'
import ConfirmDialog from '../components/brand/ConfirmDialog'
import GlowHero from '../components/brand/GlowHero'
import Tile from '../components/brand/Tile'
import { Button, FilterChip, SignalChip } from '../components/brand/primitives'
import { useFeed } from '../context/FeedContext'
import { useStats } from '../context/StatsContext'
import { friendlyError, sortInstances } from '../lib/instances'
import { useLoad } from '../lib/useLoad'
import InstanceForm from './instances/InstanceForm'
import styles from './Instances.module.css'

const fmt = new Intl.NumberFormat('en-US')
const created = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' })

/** Instances: separate brains, one active (brand book §13 "Card grid"). */
export default function Instances() {
  const [showArchived, setShowArchived] = useState(false)
  const [nonce, setNonce] = useState(0)
  const list = useLoad(() => listInstances(showArchived), `${showArchived}|${nonce}`)
  const reload = () => setNonce((n) => n + 1)
  const actions = useInstanceActions(reload)

  const data = list.data
  const sorted = data ? sortInstances(data.instances ?? [], data.active_id) : []
  const active = sorted.find((i) => i.id === data?.active_id)
  const others = sorted.filter((i) => i !== active)

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <Button variant="primary" icon="add" onClick={() => actions.setForm({ instance: null })}>
          New brain
        </Button>
        <FilterChip selected={showArchived} icon="layers" onClick={() => setShowArchived((v) => !v)}>
          Show archived
        </FilterChip>
        {actions.status && (
          <p className={`t-small ${styles.status}`} data-tone={actions.status.tone} role="status">
            {actions.status.text}
          </p>
        )}
      </div>
      {list.error && <LoadError message={list.error} onRetry={list.retry} />}
      {list.loading && !data && <p className={`t-body ${styles.secondary}`}>Loading brains…</p>}
      {data && (
        <div className={styles.grid}>
          {active && <ActiveBrain instance={active} onEdit={() => actions.setForm({ instance: active })} />}
          <AboutBrains />
          <Others list={others} actions={actions} showArchived={showArchived} />
        </div>
      )}
      <Dialogs actions={actions} />
    </div>
  )
}

/** All mutations live here, so the view stays a layout. Every one reloads the list. */
function useInstanceActions(reload) {
  const { refetch } = useStats()
  const { resetFeed } = useFeed()
  const [status, setStatus] = useState(null)
  const [switchingId, setSwitchingId] = useState(null)
  const [form, setForm] = useState(null) // { instance } | null
  const [confirm, setConfirm] = useState(null) // { kind: 'delete' | 'switch-new', instance } | null
  const fail = (e) => setStatus({ tone: 'error', text: friendlyError(e.message || String(e)) })

  async function run(fn) {
    try {
      await fn()
    } catch (e) {
      fail(e)
    } finally {
      reload()
    }
  }

  async function switchTo(instance) {
    setSwitchingId(instance.id)
    setStatus({ tone: 'info', text: `Switching to ${instance.name}…` })
    await run(async () => {
      await switchInstance(instance.id)
      await refetch?.()
      resetFeed?.()
      setStatus({ tone: 'ok', text: `Switched to ${instance.name}. Every agent now reads and writes this brain.` })
    })
    setSwitchingId(null)
  }

  async function save(body) {
    // Errors propagate to the form, which shows them and stays open.
    if (form.instance) {
      await patchInstance(form.instance.id, body)
      setStatus({ tone: 'ok', text: `Saved ${body.name}.` })
    } else {
      const record = await createInstance(body)
      setConfirm({ kind: 'switch-new', instance: record })
    }
    setForm(null)
    reload()
  }

  return {
    status,
    switchingId,
    form,
    setForm,
    confirm,
    setConfirm,
    switchTo,
    save,
    archive: (i) => run(async () => (await archiveInstance(i.id), setStatus({ tone: 'ok', text: `Archived ${i.name}.` }))),
    unarchive: (i) => run(async () => (await unarchiveInstance(i.id), setStatus({ tone: 'ok', text: `Restored ${i.name}.` }))),
    remove: async (i) => {
      await deleteInstance(i.id) // throws into the dialog, which shows the reason
      setConfirm(null)
      setStatus({ tone: 'ok', text: `Deleted ${i.name}.` })
      reload()
    },
  }
}

function ActiveBrain({ instance, onEdit }) {
  const tags = instance.tags ?? []
  return (
    <div className={styles.active}>
      <GlowHero
        label="Active brain"
        value={instance.name}
        stats={[
          { label: 'memories', value: typeof instance.memory_count === 'number' ? fmt.format(instance.memory_count) : '—' },
          ...(instance.created_at ? [{ label: 'created', value: created.format(new Date(instance.created_at)) }] : []),
          ...(tags.length ? [{ label: tags.length === 1 ? 'tag' : 'tags', value: tags.join(', ') }] : []),
        ]}
        actions={
          <Button onClick={onEdit}>
            Edit
          </Button>
        }
      />
    </div>
  )
}

function AboutBrains() {
  return (
    <Tile className={styles.about} icon="instances" title="What's a brain?" sub="Separate memories, one at a time">
      <p className={`t-body ${styles.secondary}`}>
        Each brain is its own database. Switching changes what every agent (Claude Code, Cursor, MCP) reads and writes
        from then on. Nothing moves between brains.
      </p>
      <p className={`t-small ${styles.secondary} ${styles.note}`}>
        Archive hides a brain without deleting it. Only an archived brain can be deleted, and deleting can't be undone.
      </p>
    </Tile>
  )
}

function Others({ list, actions, showArchived }) {
  if (!list.length) {
    return (
      <Tile className={styles.empty} icon="add" title="No other brains yet" sub={showArchived ? 'None archived either' : 'Archived ones are hidden'}>
        <p className={`t-body ${styles.secondary}`}>
          Make a second brain to keep, say, work and personal memories apart. You choose when to switch.
        </p>
      </Tile>
    )
  }
  return (
    <ul className={styles.cards} aria-label="Other brains">
      {list.map((i) => (
        <li key={i.id}>
          <BrainCard instance={i} actions={actions} />
        </li>
      ))}
    </ul>
  )
}

function BrainCard({ instance: i, actions }) {
  const switching = actions.switchingId === i.id
  return (
    <Tile icon="instances" title={i.name} sub={i.description || undefined}>
      <div className={styles.meta}>
        <span className="t-small">{typeof i.memory_count === 'number' ? `${fmt.format(i.memory_count)} memories` : 'Memory count unknown'}</span>
        {i.archived && <SignalChip signal="raw" icon="layers">archived</SignalChip>}
        {(i.tags ?? []).map((t) => (
          <span key={t} className={styles.tag}>{t}</span>
        ))}
      </div>
      <div className={styles.cardActions}>
        <Button icon="arrow" disabled={i.archived || actions.switchingId != null} onClick={() => actions.switchTo(i)}>
          {switching ? 'Switching…' : 'Switch to it'}
        </Button>
        <Button onClick={() => actions.setForm({ instance: i })}>Edit</Button>
        {i.archived ? <Button onClick={() => actions.unarchive(i)}>Restore</Button> : <Button onClick={() => actions.archive(i)}>Archive</Button>}
        {i.archived && <Button onClick={() => actions.setConfirm({ kind: 'delete', instance: i })}>Delete…</Button>}
      </div>
    </Tile>
  )
}

function Dialogs({ actions }) {
  const c = actions.confirm
  const close = () => actions.setConfirm(null)
  return (
    <>
      <InstanceForm open={!!actions.form} instance={actions.form?.instance ?? null} onSubmit={actions.save} onClose={() => actions.setForm(null)} />
      <ConfirmDialog
        open={c?.kind === 'delete'}
        title={`Delete ${c?.instance.name ?? ''}?`}
        confirmLabel="Delete brain"
        danger
        onConfirm={() => actions.remove(c.instance)}
        onCancel={close}
      >
        <p>All of its memories are deleted and this can't be undone.</p>
        <p className={`t-mono ${styles.path}`}>{c?.instance.db_path}</p>
      </ConfirmDialog>
      <ConfirmDialog
        open={c?.kind === 'switch-new'}
        title={`Switch to ${c?.instance.name ?? ''} now?`}
        confirmLabel="Switch now"
        onConfirm={async () => (close(), await actions.switchTo(c.instance))}
        onCancel={close}
      >
        <p>It's empty. Every agent will start saving here instead of the current brain.</p>
      </ConfirmDialog>
    </>
  )
}

function LoadError({ message, onRetry }) {
  return (
    <div className={`t-small ${styles.error}`} role="alert">
      <span>Couldn't load brains ({friendlyError(message)}).</span>
      <Button onClick={onRetry}>Retry</Button>
    </div>
  )
}

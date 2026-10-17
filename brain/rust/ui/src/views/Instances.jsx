import { useEffect, useState } from 'react'
import {
  archiveInstance,
  createInstance,
  deleteInstance,
  listInstances,
  patchInstance,
  switchInstance,
  unarchiveInstance,
} from '../api'
import { useFeed } from '../context/FeedContext'
import { useStats } from '../context/StatsContext'

function sortInstances(instances, activeId) {
  return [...instances].sort((a, b) => {
    if (a.id === activeId) return -1
    if (b.id === activeId) return 1
    return a.name.localeCompare(b.name)
  })
}

function EditForm({ instance, onSave, onCancel }) {
  const [name, setName] = useState(instance.name)
  const [description, setDescription] = useState(instance.description || '')
  const [tags, setTags] = useState((instance.tags || []).join(', '))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    setError(null)
    try {
      await onSave({
        name: name.trim(),
        description,
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      })
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 space-y-2 border-t border-zinc-800 pt-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name"
        className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description"
        className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
      />
      <input
        value={tags}
        onChange={(e) => setTags(e.target.value)}
        placeholder="Tags (comma-separated)"
        className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-zinc-200 px-2.5 py-1 text-xs font-medium text-black disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded px-2.5 py-1 text-xs text-zinc-400 hover:text-zinc-200"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

function NewInstanceForm({ onCreated }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    setError(null)
    try {
      const record = await createInstance({
        name: name.trim(),
        description,
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      })
      setName('')
      setDescription('')
      setTags('')
      setOpen(false)
      await onCreated(record)
    } catch (err) {
      setError(err.message)
    } finally {
      setCreating(false)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-500 hover:text-white"
      >
        + New instance
      </button>
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded border border-zinc-800 bg-zinc-950 p-3 space-y-2 max-w-md"
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name"
        autoFocus
        className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description"
        className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
      />
      <input
        value={tags}
        onChange={(e) => setTags(e.target.value)}
        placeholder="Tags (comma-separated)"
        className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={creating}
          className="rounded bg-zinc-200 px-2.5 py-1 text-xs font-medium text-black disabled:opacity-50"
        >
          {creating ? 'Creating…' : 'Create'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded px-2.5 py-1 text-xs text-zinc-400 hover:text-zinc-200"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

function InstanceRow({
  instance,
  isActive,
  switching,
  switchDisabled,
  onSwitch,
  onArchive,
  onUnarchive,
  onDelete,
  onEdit,
}) {
  const [editing, setEditing] = useState(false)

  async function handleSave(body) {
    await onEdit(instance.id, body)
    setEditing(false)
  }

  return (
    <div className="border-b border-zinc-800 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-white">{instance.name}</p>
            {isActive && (
              <span className="rounded-full bg-emerald-900/40 px-2 py-0.5 text-[11px] text-emerald-400">
                Active
              </span>
            )}
            {instance.archived && (
              <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-500">
                Archived
              </span>
            )}
          </div>
          {instance.description && (
            <p className="mt-0.5 text-xs text-zinc-500">{instance.description}</p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-zinc-600">
            {instance.memory_count != null && <span>{instance.memory_count} memories</span>}
            {(instance.tags || []).map((t) => (
              <span key={t} className="rounded bg-zinc-900 px-1.5 py-0.5">
                {t}
              </span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            disabled={switchDisabled}
            onClick={() => onSwitch(instance.id)}
            className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500 hover:text-white disabled:opacity-40 disabled:hover:border-zinc-700"
          >
            {switching ? 'Switching…' : 'Switch'}
          </button>
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500 hover:text-white"
          >
            Edit
          </button>
          {instance.archived ? (
            <button
              type="button"
              onClick={() => onUnarchive(instance.id)}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500 hover:text-white"
            >
              Unarchive
            </button>
          ) : (
            <button
              type="button"
              disabled={isActive}
              onClick={() => onArchive(instance.id)}
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:border-zinc-500 hover:text-white disabled:opacity-40 disabled:hover:border-zinc-700"
            >
              Archive
            </button>
          )}
          {instance.archived && (
            <button
              type="button"
              onClick={() => onDelete(instance.id, instance.name, instance.db_path)}
              className="rounded border border-red-900 px-2 py-1 text-xs text-red-400 hover:border-red-700 hover:text-red-300"
            >
              Delete
            </button>
          )}
        </div>
      </div>
      {editing && (
        <EditForm instance={instance} onSave={handleSave} onCancel={() => setEditing(false)} />
      )}
    </div>
  )
}

export default function Instances() {
  const [instances, setInstances] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [showArchived, setShowArchived] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [statusMsg, setStatusMsg] = useState(null)
  const [switchingId, setSwitchingId] = useState(null)
  const { refetch } = useStats()
  const { resetFeed } = useFeed()

  async function load(archived) {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await listInstances(archived)
      setInstances(data.instances || [])
      setActiveId(data.active_id ?? null)
    } catch (e) {
      setLoadError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(showArchived)
  }, [showArchived])

  async function handleSwitch(id, displayName) {
    setStatusMsg('Switching instance…')
    setSwitchingId(id)
    try {
      await switchInstance(id)
      await refetch?.()
      resetFeed?.()
      const target = instances.find((i) => i.id === id)
      setStatusMsg(`Switched to ${displayName || target?.name || id}`)
      await load(showArchived)
    } catch (e) {
      const msg = /\b(503|500)\b/.test(e.message)
        ? 'Server busy switching instances — try again shortly.'
        : e.message
      setStatusMsg(msg)
    } finally {
      setSwitchingId(null)
    }
  }

  async function handleCreated(record) {
    await load(showArchived)
    if (window.confirm('Switch to new instance now?')) {
      await handleSwitch(record.id, record.name)
    }
  }

  async function handleEdit(id, body) {
    await patchInstance(id, body)
    await load(showArchived)
  }

  async function handleArchive(id) {
    try {
      await archiveInstance(id)
      await load(showArchived)
    } catch (e) {
      setStatusMsg(e.message)
    }
  }

  async function handleUnarchive(id) {
    try {
      await unarchiveInstance(id)
      await load(showArchived)
    } catch (e) {
      setStatusMsg(e.message)
    }
  }

  async function handleDelete(id, name, dbPath) {
    if (!window.confirm(`Delete instance "${name}"?\n\nThis cannot be undone.\n\nDB: ${dbPath}`)) return
    try {
      await deleteInstance(id)
      await load(showArchived)
    } catch (e) {
      setStatusMsg(e.message)
    }
  }

  const sorted = sortInstances(instances, activeId)

  return (
    <div className="p-4 max-w-3xl">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Instances</h2>
        <label className="flex items-center gap-2 text-xs text-zinc-500">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          Show archived
        </label>
      </div>

      <div className="mb-4">
        <NewInstanceForm onCreated={handleCreated} />
      </div>

      {statusMsg && (
        <div className="mb-3 rounded bg-zinc-900 px-3 py-2 text-xs text-zinc-300">
          {statusMsg}
        </div>
      )}

      {loadError && (
        <div className="mb-3 flex items-center justify-between rounded bg-red-900/20 p-2 text-xs text-red-400">
          {loadError}
          <button type="button" onClick={() => load(showArchived)} className="underline ml-2">
            Retry
          </button>
        </div>
      )}

      {loading && <p className="text-sm text-zinc-600">Loading…</p>}

      {!loading && sorted.length === 0 && (
        <p className="text-sm text-zinc-600 py-4">No instances found.</p>
      )}

      <div>
        {sorted.map((instance) => (
          <InstanceRow
            key={instance.id}
            instance={instance}
            isActive={instance.id === activeId}
            switching={switchingId === instance.id}
            switchDisabled={
              instance.id === activeId || instance.archived || switchingId != null
            }
            onSwitch={handleSwitch}
            onArchive={handleArchive}
            onUnarchive={handleUnarchive}
            onDelete={handleDelete}
            onEdit={handleEdit}
          />
        ))}
      </div>
    </div>
  )
}

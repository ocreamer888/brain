import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { listMemories, streamUrl } from '../api'

const FeedContext = createContext(null)

export function FeedProvider({ children }) {
  const [feed, setFeed] = useState([])
  const [status, setStatus] = useState('connecting') // connecting | live | reconnecting
  const seen = useRef(new Set())

  function seedFeed(cancelledRef) {
    listMemories(25)
      .then((data) => {
        if (cancelledRef && cancelledRef.current) return
        const items = (data.items || []).map((m) => ({
          id: m.id,
          content_snippet: (m.content || '').slice(0, 200),
          timestamp: m.timestamp,
          memory_type: m.memory_type,
          _seeded: true,
        }))
        for (const it of items) seen.current.add(it.id)
        setFeed(items)
      })
      .catch(() => {
        /* seed is best-effort */
      })
  }

  useEffect(() => {
    const cancelledRef = { current: false }
    seedFeed(cancelledRef)
    return () => {
      cancelledRef.current = true
    }
  }, [])

  function resetFeed() {
    seen.current = new Set()
    setFeed([])
    seedFeed()
  }

  useEffect(() => {
    let es
    let retryTimer
    let closed = false

    function connect() {
      if (closed) return
      setStatus((s) => (s === 'live' ? 'reconnecting' : 'connecting'))
      es = new EventSource(streamUrl())
      es.onopen = () => setStatus('live')
      es.onmessage = (e) => {
        try {
          const evt = JSON.parse(e.data)
          setStatus('live')
          setFeed((prev) => {
            // Dedupe consecutive identical ids but allow re-show after others.
            const next = [evt, ...prev.filter((x) => x.id !== evt.id)].slice(0, 200)
            seen.current.add(evt.id)
            return next
          })
        } catch {
          /* ignore */
        }
      }
      es.onerror = () => {
        setStatus('reconnecting')
        try {
          es.close()
        } catch {
          /* ignore */
        }
        if (!closed) {
          retryTimer = setTimeout(connect, 1500)
        }
      }
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      try {
        es?.close()
      } catch {
        /* ignore */
      }
    }
  }, [])

  return (
    <FeedContext.Provider value={{ feed, status, resetFeed }}>
      {children}
    </FeedContext.Provider>
  )
}

export function useFeed() {
  return useContext(FeedContext)
}

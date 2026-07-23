'use client'

// Kept in its own file, loaded only via next/dynamic({ ssr: false }) from
// Workspace.tsx: @xterm/xterm references browser-only globals (`self`) at
// module-evaluation time, which crashes Next.js's server-side render pass
// if this module is ever pulled into the SSR bundle. A plain top-level
// import here would still get bundled server-side even inside a 'use
// client' file, since Next.js SSRs client components for the initial HTML
// too - only a dynamic(), ssr:false boundary keeps this module
// client-only. Confirmed by reproducing the exact SSR crash
// ("ReferenceError: self is not defined") with a plain import before this
// split, and a clean `next build` after it.
import { useCallback, useEffect, useRef, useState } from 'react'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { RefreshCw, ShieldCheck } from './Icons'
import { API_URL } from '@/lib/api'

function terminalWebSocketUrl(path: string): string {
  const wsBase = API_URL.replace(/^http/i, 'ws')
  return `${wsBase}/ws/terminal?path=${encodeURIComponent(path)}`
}

export function TerminalView({ initialPath }: { initialPath?: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<XTerm | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const [pathInput, setPathInput] = useState(initialPath || '')
  const [connected, setConnected] = useState(false)
  const [status, setStatus] = useState('Not connected.')

  const connect = useCallback((path: string) => {
    const term = termRef.current
    if (!term) return
    socketRef.current?.close()
    term.reset()
    setStatus('Connecting…')
    const socket = new WebSocket(terminalWebSocketUrl(path || '.'))
    socket.binaryType = 'arraybuffer'
    socketRef.current = socket
    socket.onopen = () => { setConnected(true); setStatus('Connected') }
    socket.onclose = () => { setConnected(false); setStatus('Disconnected') }
    socket.onerror = () => setStatus('Connection error - is the API running?')
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const payload = JSON.parse(event.data) as { type?: string; message?: string }
          if (payload.type === 'error') { term.writeln(`\r\n[InMyAI] ${payload.message ?? 'Terminal error.'}`); setStatus(payload.message ?? 'Terminal error.') }
          if (payload.type === 'exit') { term.writeln('\r\n[InMyAI] Session ended.'); setConnected(false) }
        } catch { /* not JSON, ignore */ }
        return
      }
      const bytes = event.data instanceof ArrayBuffer ? new Uint8Array(event.data) : (event.data as Uint8Array)
      term.write(bytes)
    }
  }, [])

  useEffect(() => {
    if (!containerRef.current || termRef.current) return
    let disposed = false
    const term = new XTerm({
      convertEol: true,
      fontSize: 12,
      fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
      theme: { background: '#151a22', foreground: '#e6e9ef' }
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(containerRef.current)
    termRef.current = term

    // The first fit() is deferred to the next animation frame instead of
    // being called synchronously right after term.open(): xterm's renderer
    // needs one real layout/paint pass before FitAddon can safely measure
    // character dimensions, and fitting too early is a documented source
    // of "Cannot read properties of undefined (reading 'dimensions')"
    // crashes. This is what you hit - Next.js dev mode's React Strict Mode
    // double-invokes this effect (mount -> cleanup -> mount again), which
    // makes that race far easier to trigger locally than it would be in a
    // normal single-mount production build, but it's worth guarding
    // against unconditionally rather than relying on StrictMode being off.
    const raf = requestAnimationFrame(() => {
      if (disposed) return
      fit.fit()
    })

    const dataSubscription = term.onData((data: string) => {
      const socket = socketRef.current
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'input', data }))
    })

    connect(pathInput)

    const resizeObserver = new ResizeObserver(() => {
      // Guard against a queued resize callback firing after this effect
      // instance was already torn down (StrictMode double-invoke, or a
      // fast tab switch away from Terminal) - calling fit()/reading
      // term.cols on an already-disposed terminal is exactly what throws
      // the "reading 'dimensions'" error seen in the dev overlay.
      if (disposed || termRef.current !== term) return
      fit.fit()
      const socket = socketRef.current
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      dataSubscription.dispose()
      resizeObserver.disconnect()
      socketRef.current?.close()
      term.dispose()
      if (termRef.current === term) termRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function reconnect(event: React.FormEvent) {
    event.preventDefault()
    connect(pathInput)
  }

  return (
    <div className="terminal-layout">
      <div className="explorer-toolbar">
        <form onSubmit={reconnect}>
          <input value={pathInput} onChange={(event) => setPathInput(event.target.value)} placeholder="Working directory (defaults to the API's own folder)"/>
          <button className="primary small"><RefreshCw size={13}/>{connected ? 'Restart here' : 'Connect'}</button>
        </form>
        <span className={`status ${connected ? 'applied' : 'pending'}`}>{status}</span>
      </div>
      <div className="terminal-canvas" ref={containerRef}/>
      <div className="safety-box terminal-warning"><ShieldCheck size={18}/><div><strong>Not sandboxed</strong><p>This is a real shell under your own account - the same access as any terminal window you open yourself. Nothing here is restricted by InMyAI's file-access policy.</p></div></div>
    </div>
  )
}

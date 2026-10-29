import { Link, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

const NAV = [
  { to: '/', label: 'Home' },
  { to: '/simulator', label: 'Simulator' },
  { to: '/comparison', label: 'Comparison' },
  { to: '/timeline', label: 'Blockage timeline' },
  { to: '/methodology', label: 'Methodology' },
]

export default function Layout({ children, llmBadge }: { children: ReactNode; llmBadge?: string }) {
  const loc = useLocation()
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-white/10 bg-white/5 backdrop-blur sticky top-0 z-30">
        <div className="mx-auto max-w-7xl px-4 h-14 flex items-center gap-6">
          <Link to="/" className="font-semibold tracking-tight text-lg flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full bg-yellow-300 shadow-[0_0_12px_rgba(255,255,150,.9)]" />
            LumiSteer
          </Link>
          <nav className="flex gap-1 text-sm overflow-x-auto thin-scroll">
            {NAV.map(n => (
              <Link key={n.to} to={n.to}
                className={`px-3 py-1.5 rounded-full whitespace-nowrap ${loc.pathname === n.to ? 'bg-white/15 text-white' : 'text-white/70 hover:text-white hover:bg-white/5'}`}>
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto text-xs text-white/60">{llmBadge}</div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-white/10 py-4 text-center text-xs text-white/40">
        LumiSteer · Nebius x NVIDIA Global AI Hackathon · all numbers computed by the physics engine
      </footer>
    </div>
  )
}

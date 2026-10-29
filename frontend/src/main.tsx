import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import LandingPage from './pages/LandingPage'
import SimulatorPage from './pages/SimulatorPage'
import ComparisonPage from './pages/ComparisonPage'
import TimelinePage from './pages/TimelinePage'
import MethodologyPage from './pages/MethodologyPage'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <HashRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/simulator" element={<SimulatorPage />} />
        <Route path="/comparison" element={<ComparisonPage />} />
        <Route path="/timeline" element={<TimelinePage />} />
        <Route path="/methodology" element={<MethodologyPage />} />
      </Routes>
    </HashRouter>
  </React.StrictMode>,
)

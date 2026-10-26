import { NavLink, Route, Routes } from 'react-router-dom';
import clsx from 'clsx';
import { useStore } from './api/store';
import { SimControls } from './components/SimControls';
import Dashboard from './pages/Dashboard';
import EnvironmentMap from './pages/EnvironmentMap';
import AgentControlRoom from './pages/AgentControlRoom';
import CommunicationCenter from './pages/CommunicationCenter';
import MissionInspector from './pages/MissionInspector';

const NAV = [
  { to: '/', label: 'Dashboard', exact: true },
  { to: '/map', label: 'Environment' },
  { to: '/agents', label: 'Agent Control Room' },
  { to: '/comms', label: 'Communication Center' },
  { to: '/missions', label: 'Mission Inspector' },
];

export default function App() {
  const { connected } = useStore();

  return (
    <div className="flex h-screen w-screen flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center gap-4 border-b border-neutral-800 bg-neutral-900 px-4 py-2.5">
        <h1 className="text-sm font-semibold tracking-tight">Multi-Agent Cognitive Robot System</h1>
        <nav className="flex gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.exact}
              className={({ isActive }) =>
                clsx(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition',
                  isActive ? 'bg-indigo-600 text-white' : 'text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200',
                )
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1.5 text-xs text-neutral-400">
          <span className={clsx('inline-block h-2 w-2 rounded-full', connected ? 'bg-emerald-500' : 'bg-rose-500')} />
          {connected ? 'live' : 'reconnecting…'}
        </div>
      </header>

      <SimControls />

      <main className="min-h-0 flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/map" element={<EnvironmentMap />} />
          <Route path="/agents" element={<AgentControlRoom />} />
          <Route path="/comms" element={<CommunicationCenter />} />
          <Route path="/missions" element={<MissionInspector />} />
          <Route path="/missions/:missionId" element={<MissionInspector />} />
        </Routes>
      </main>
    </div>
  );
}

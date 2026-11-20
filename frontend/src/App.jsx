import { useState } from 'react';
import { Clapperboard, Settings2 } from 'lucide-react';
import { useCurrency, useHashRoute } from './lib/hooks';
import { setCurrency } from './lib/money';
import Landing from './pages/Landing';
import Brief from './pages/Brief';
import Job from './pages/Job';
import Privacy from './pages/Privacy';

const V1_URL = 'https://ugc-creator-4a20yqpyc-aimilios-projects-21450502.vercel.app';

function Nav({ route }) {
  const active = (path) => (route === path || (path !== '/' && route.startsWith(path)) ? 'nav-link active' : 'nav-link');
  return (
    <header className="nav">
      <a href="#/" className="brand">
        <Clapperboard size={20} aria-hidden="true" />
        <span>UGC Ad Builder</span>
      </a>
      <nav className="nav-links" aria-label="Main">
        <a href="#/" className={active('/')}>Home</a>
        <a href="#/create" className={active('/create')}>Create ad</a>
        <a href="#/privacy" className={active('/privacy')}>Privacy</a>
      </nav>
    </header>
  );
}

function Footer() {
  const currency = useCurrency();
  const [open, setOpen] = useState(false);
  return (
    <footer className="footer">
      <button type="button" className="btn btn-ghost btn-small" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Settings2 size={14} aria-hidden="true" /> Advanced settings
      </button>
      {open && (
        <div className="advanced-panel">
          <label htmlFor="currency">Display currency</label>
          <select id="currency" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            <option value="EUR">EUR (default)</option>
            <option value="USD">USD</option>
          </select>
          <p className="muted small">Providers bill in USD; the app converts at one fixed rate.</p>
        </div>
      )}
      <p className="muted small footer-links">
        <span>UGC Ad Builder v2</span>
        <a href="https://github.com/Aimilios94/UGC-Creator" target="_blank" rel="noreferrer">
          GitHub
        </a>
        <a href="https://github.com/Aimilios94/UGC-Creator/tree/main/docs" target="_blank" rel="noreferrer">
          Docs
        </a>
        <a href={V1_URL} target="_blank" rel="noreferrer">
          v1 (n8n prototype)
        </a>
        <a href="#/privacy">Privacy notice</a>
      </p>
    </footer>
  );
}

export default function App() {
  const route = useHashRoute();
  let page;
  if (route.startsWith('/job/')) {
    const [jobId, view] = route.slice(5).split('/');
    page = <Job key={route} jobId={jobId} view={view || ''} />;
  }
  else if (route === '/create') page = <Brief />;
  else if (route === '/privacy') page = <Privacy />;
  else page = <Landing />;
  return (
    <div className="app">
      <Nav route={route} />
      <main className="main">{page}</main>
      <Footer />
    </div>
  );
}

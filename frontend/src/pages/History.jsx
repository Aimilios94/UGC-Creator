import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Clapperboard, ImageOff, Loader2 } from 'lucide-react';
import { api } from '../lib/api';
import { useCurrency } from '../lib/hooks';
import { formatMoney } from '../lib/money';

// History (M2 item 4): this browser's ads, newest first, with what each one cost and, on request,
// what each step cost. The server lists only this browser's ads.
const THEME_TITLE = { sport: 'Sport', beauty: 'Beauty', tech: 'Tech', food: 'Food', fashion: 'Fashion' };

function statusLabel(row) {
  if (row.status === 'draft') return 'Storyboard, not made yet';
  if (row.status === 'queued' || row.status === 'running') return row.phase === 'images' ? 'Making the pictures' : 'Making the video';
  if (row.status === 'failed') return 'Stopped';
  return row.phase === 'images' ? 'Pictures ready' : 'Video ready';
}

const when = (iso) =>
  new Intl.DateTimeFormat('en-IE', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));

function StageCosts({ id, currency }) {
  const [stages, setStages] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api.getJob(id).then((j) => setStages(j.stage_costs), (err) => setError(err.message));
  }, [id]);
  if (error) return <p className="error small">{error}</p>;
  if (!stages)
    return (
      <p className="muted small">
        <Loader2 className="spin" size={14} aria-hidden="true" /> Loading the costs…
      </p>
    );
  if (!stages.length) return <p className="muted small">Nothing was paid for this ad.</p>;
  return (
    <table className="stage-costs small">
      <tbody>
        {stages.map((s) => (
          <tr key={s.stage}>
            <td>{s.label}</td>
            <td className="muted">
              {s.calls} {s.calls === 1 ? 'call' : 'calls'}
            </td>
            <td className="num">{formatMoney(s.cost, currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function History() {
  const currency = useCurrency();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState('');
  useEffect(() => {
    api.history().then(setRows, (err) => setError(err.message));
  }, []);

  const total = rows?.reduce((acc, r) => ({ usd: acc.usd + r.cost.usd, eur: acc.eur + r.cost.eur }), { usd: 0, eur: 0 });
  return (
    <div className="page history">
      <h1>Your ads</h1>
      <p className="muted">The ads made in this browser, newest first, with what each one cost. Nobody else can see them.</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!rows && !error && (
        <p className="muted">
          <Loader2 className="spin" size={16} aria-hidden="true" /> Loading…
        </p>
      )}
      {rows && rows.length === 0 && (
        <div className="card empty">
          <Clapperboard size={20} aria-hidden="true" />
          <p>No ads yet in this browser.</p>
          <a href="#/create" className="btn btn-primary btn-small">
            Create an ad
          </a>
        </div>
      )}
      {rows && rows.length > 0 && (
        <>
          <ul className="history-list">
            {rows.map((r) => (
              <li key={r.id} className="card history-row">
                <a href={`#/job/${r.id}`} className="history-thumb" aria-label={`Open ${r.product_name}`}>
                  {r.picture_url ? <img src={r.picture_url} alt="" loading="lazy" /> : <ImageOff size={20} aria-hidden="true" />}
                </a>
                <div className="history-main">
                  <a href={`#/job/${r.id}`} className="history-name">
                    {r.product_name}
                  </a>
                  <p className="muted small">
                    {when(r.created_at)}
                    {r.theme ? ` · ${THEME_TITLE[r.theme] ?? r.theme}` : ''} · <span className={`status-${r.status}`}>{statusLabel(r)}</span>
                  </p>
                  <button
                    type="button"
                    className="link-btn small"
                    aria-expanded={open === r.id}
                    onClick={() => setOpen(open === r.id ? '' : r.id)}
                  >
                    Cost per step {open === r.id ? <ChevronUp size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
                  </button>
                  {open === r.id && <StageCosts id={r.id} currency={currency} />}
                </div>
                <strong className="history-cost">{formatMoney(r.cost, currency)}</strong>
              </li>
            ))}
          </ul>
          <p className="history-total">
            <span>
              Total for {rows.length} {rows.length === 1 ? 'ad' : 'ads'}
            </span>
            <strong>{formatMoney(total, currency)}</strong>
          </p>
          <p className="muted small">
            Costs are what the AI providers charge, converted from USD at one fixed rate. A local test with no AI shows
            what a real run would cost.
          </p>
        </>
      )}
    </div>
  );
}

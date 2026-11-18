import { useEffect, useState } from 'react';
import { CheckCircle2, Circle, Loader2, RotateCcw, XCircle } from 'lucide-react';
import { api, rememberJob } from '../lib/api';
import { navigate, useCurrency } from '../lib/hooks';
import { formatMoney } from '../lib/money';
import { Stepper } from './Brief';

const POLL_MS = 3000;
const ROLE_LABEL = { hook: 'Scene 1 · Hook', demo: 'Scene 2 · Demo', cta: 'Scene 3 · Call to action' };
const FORMULA_LABEL = {
  pov: 'POV',
  problem_first: 'Problem first',
  three_reasons: '3 reasons',
  unboxing_tease: 'Unboxing tease',
};

const isActive = (j) => j.status === 'queued' || j.status === 'running';

export default function Job({ jobId }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const [round, setRound] = useState(0); // bumping it restarts polling

  useEffect(() => {
    let cancelled = false;
    let timer;
    async function poll() {
      try {
        const j = await api.getJob(jobId);
        if (cancelled) return;
        setJob(j);
        setError('');
        rememberJob(j.id);
        if (isActive(j)) timer = setTimeout(poll, POLL_MS);
      } catch (err) {
        if (cancelled) return;
        setError(
          err.status === 404 ? 'This ad was not found. It can only be opened in the browser that created it.' : err.message,
        );
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, round]);

  const update = (j) => {
    setJob(j);
    if (isActive(j)) setRound((r) => r + 1);
  };

  if (error && !job) {
    return (
      <div className="page">
        <div className="card narrow">
          <p className="error" role="alert">{error}</p>
          <a className="btn btn-secondary" href="#/create">Start a new ad</a>
        </div>
      </div>
    );
  }
  if (!job) {
    return (
      <div className="page center">
        <Loader2 className="spin" size={28} aria-label="Loading" />
      </div>
    );
  }
  if (job.status === 'draft') return <StoryboardStep job={job} onChange={update} />;
  return <GenerateStep job={job} onChange={update} />;
}

function StoryboardStep({ job, onChange }) {
  const currency = useCurrency();
  const [board, setBoard] = useState(job.storyboard);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [estimate, setEstimate] = useState(null);

  useEffect(() => {
    api.config().then((c) => setEstimate(c.job_estimate), () => {});
  }, []);

  if (!board) {
    return (
      <div className="page">
        <Stepper step={2} />
        <div className="card narrow">
          <h2>No storyboard yet</h2>
          <p className="error" role="alert">{job.last_error || 'The storyboard could not be written.'}</p>
          <button className="btn btn-primary" onClick={() => navigate('/create')}>Start again</button>
        </div>
      </div>
    );
  }

  const editScene = (i, field) => (e) => {
    const scenes = board.scenes.map((s, j) => (j === i ? { ...s, [field]: e.target.value } : s));
    setBoard({ ...board, scenes });
    setDirty(true);
  };

  async function approve() {
    setBusy(true);
    setError('');
    try {
      if (dirty) await api.saveStoryboard(job.id, board);
      onChange(await api.approve(job.id));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Stepper step={2} />
      <div className="row between">
        <h1>{board.title}</h1>
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}>
          {advanced ? 'Hide' : 'Show'} advanced fields
        </button>
      </div>
      <p className="muted">
        Edit anything, then approve. Nothing is rendered before you approve. This version renders scene 1; full 3-scene
        ads come next.
      </p>

      <div className="scenes">
        {board.scenes.map((s, i) => (
          <article key={s.role} className="card scene">
            <h2>{ROLE_LABEL[s.role]}</h2>
            <label htmlFor={`d${i}`}>What we see</label>
            <textarea id={`d${i}`} rows={3} value={s.description} onChange={editScene(i, 'description')} maxLength={500} />
            <label htmlFor={`v${i}`}>Voiceover</label>
            <input id={`v${i}`} value={s.voiceover} onChange={editScene(i, 'voiceover')} maxLength={220} />
            <label htmlFor={`t${i}`}>On-screen text</label>
            <input id={`t${i}`} value={s.on_screen_text} onChange={editScene(i, 'on_screen_text')} maxLength={80} />
            {advanced && (
              <>
                <label htmlFor={`ip${i}`}>Image prompt</label>
                <textarea id={`ip${i}`} rows={4} value={s.image_prompt} onChange={editScene(i, 'image_prompt')} maxLength={1200} />
                <label htmlFor={`mp${i}`}>Motion prompt</label>
                <textarea id={`mp${i}`} rows={2} value={s.motion_prompt} onChange={editScene(i, 'motion_prompt')} maxLength={600} />
              </>
            )}
          </article>
        ))}
      </div>

      <section className="card">
        <h2>Hook ideas for scene 1</h2>
        <ul className="hooks">
          {board.hooks.map((h) => (
            <li key={h.formula + h.text}>
              <span className="pill">{FORMULA_LABEL[h.formula]}</span> {h.text}
            </li>
          ))}
        </ul>
        <p className="muted small">Hook Lab, which renders and ranks all three, arrives in a later version.</p>
      </section>

      <div className="actions">
        {error && <p className="error" role="alert">{error}</p>}
        <p className="muted small">
          Approving renders scene 1 (one reference image and a 5-second clip)
          {estimate && <> for about {formatMoney(estimate, currency)}</>}, under a cap of{' '}
          {formatMoney(job.cost_cap, currency)} per ad.
        </p>
        <button className="btn btn-primary" onClick={approve} disabled={busy}>
          {busy ? 'Approving…' : 'Approve and generate'}
        </button>
      </div>
    </div>
  );
}

const STAGE_LABEL = {
  analyze: 'Read the product photo',
  storyboard: 'Write the storyboard',
  image: 'Reference image',
  video: 'Video clip',
};

function StageIcon({ status }) {
  if (status === 'done') return <CheckCircle2 size={18} className="ok" aria-label="done" />;
  if (status === 'failed') return <XCircle size={18} className="bad" aria-label="failed" />;
  if (status === 'running' || status === 'submitted') return <Loader2 size={18} className="spin" aria-label="in progress" />;
  return <Circle size={18} className="muted" aria-label="waiting" />;
}

function GenerateStep({ job, onChange }) {
  const currency = useCurrency();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const video = job.assets.find((a) => a.kind === 'video');
  const image = job.assets.find((a) => a.kind === 'image');
  const expected = [
    { stage: 'analyze', scene_idx: -1 },
    { stage: 'storyboard', scene_idx: -1 },
    { stage: 'image', scene_idx: 0 },
    { stage: 'video', scene_idx: 0 },
  ];
  const stageStatus = (st) =>
    job.stages.find((s) => s.stage === st.stage && s.scene_idx === st.scene_idx) || { status: 'waiting' };
  const active = job.status === 'queued' || job.status === 'running';

  async function retry() {
    setBusy(true);
    setError('');
    try {
      onChange(await api.retry(job.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Stepper step={3} />
      <h1>{job.storyboard?.title || 'Your ad'}</h1>
      <div className="grid-2">
        <section className="card">
          <h2>Progress</h2>
          <ul className="stages">
            {expected.map((st) => {
              const s = stageStatus(st);
              return (
                <li key={st.stage}>
                  <StageIcon status={s.status} />
                  <span>{STAGE_LABEL[st.stage]}{st.scene_idx >= 0 ? ' (scene 1)' : ''}</span>
                  {s.error && <span className="error small">{s.error}</span>}
                </li>
              );
            })}
          </ul>
          <p className="cost" aria-live="polite">
            Spent so far: <strong>{formatMoney(job.spend, currency)}</strong>{' '}
            <span className="muted">of a {formatMoney(job.cost_cap, currency)} cap</span>
          </p>
          {active && (
            <p className="muted small">
              You can close this tab: rendering continues on the server. Come back to this page in this browser to see
              the result.
            </p>
          )}
          {job.status === 'failed' && (
            <div className="failed">
              <p className="error" role="alert">{job.last_error || 'The job failed.'}</p>
              <p className="muted small">Trying again keeps the finished steps. Spend so far still counts toward the cap.</p>
              <button className="btn btn-secondary" onClick={retry} disabled={busy}>
                <RotateCcw size={16} aria-hidden="true" /> Try again
              </button>
              {error && <p className="error">{error}</p>}
            </div>
          )}
        </section>

        <section className="card media">
          {video ? (
            <video src={video.url} controls playsInline poster={image?.url} className={`ratio-${job.brief.aspect_ratio.replace(':', 'x')}`} />
          ) : image ? (
            <img src={image.url} alt="Reference image for scene 1" className={`ratio-${job.brief.aspect_ratio.replace(':', 'x')}`} />
          ) : (
            <div className="placeholder">
              <Loader2 className={active ? 'spin' : ''} size={28} aria-hidden="true" />
              <span className="muted">{active ? 'Rendering…' : 'No media yet'}</span>
            </div>
          )}
          {job.status === 'done' && <p className="ok small">Done. Links to the files expire after a few minutes; reload to refresh them.</p>}
        </section>
      </div>
    </div>
  );
}

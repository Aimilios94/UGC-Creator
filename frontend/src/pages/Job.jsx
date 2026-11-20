import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Circle, Loader2, RotateCcw, XCircle } from 'lucide-react';
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
  const [config, setConfig] = useState(null);

  useEffect(() => {
    api.config().then(setConfig, () => {});
  }, []);

  const flags = job.flags || [];
  const cls = (field) => (flags.some((f) => f.field === field) ? 'flagged' : undefined);
  const scenesN = config?.render_scenes ?? 3;

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
  const editTop = (field) => (e) => {
    setBoard({ ...board, [field]: e.target.value });
    setDirty(true);
  };
  const editHook = (i) => (e) => {
    setBoard({ ...board, hooks: board.hooks.map((h, j) => (j === i ? { ...h, text: e.target.value } : h)) });
    setDirty(true);
  };

  async function save() {
    const saved = await api.saveStoryboard(job.id, board);
    setDirty(false);
    onChange(saved);
    return saved;
  }

  async function approve() {
    setBusy(true);
    setError('');
    try {
      const current = dirty ? await save() : job;
      if ((current.flags || []).length) {
        setError('Some lines still need editing (marked above).');
        setBusy(false);
        return;
      }
      onChange(await api.approve(job.id));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  async function check() {
    setBusy(true);
    setError('');
    try {
      await save();
    } catch (err) {
      setError(err.message);
    } finally {
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
      <p className="muted">Edit anything, then approve. Nothing is rendered before you approve.</p>

      {flags.length > 0 && (
        <div className="notice flag-notice" role="status">
          <AlertTriangle size={16} aria-hidden="true" />
          <div>
            <strong>
              {flags.length} {flags.length === 1 ? 'line needs' : 'lines need'} editing before you approve.
            </strong>{' '}
            An ad may only claim use, results, reviews or awards that your brief states. Rewrite the marked lines, then
            check again.
            <ul>
              {flags.map((f) => (
                <li key={f.field + f.text}>
                  “{f.text}” <span className="muted">({f.reason})</span>
                </li>
              ))}
            </ul>
            <button type="button" className="btn btn-secondary btn-small" onClick={check} disabled={busy}>
              Check again
            </button>
          </div>
        </div>
      )}

      <section className="card">
        <div className="grid-2 tight">
          <div>
            <label htmlFor="title">Title</label>
            <input id="title" className={cls('title')} value={board.title} onChange={editTop('title')} maxLength={100} />
          </div>
          <div>
            <label htmlFor="cta">Call to action</label>
            <input
              id="cta"
              className={cls('cta_text')}
              value={board.cta_text}
              onChange={editTop('cta_text')}
              maxLength={60}
            />
          </div>
        </div>
      </section>

      <div className="scenes">
        {board.scenes.map((s, i) => (
          <article key={s.role} className="card scene">
            <h2>{ROLE_LABEL[s.role]}</h2>
            <label htmlFor={`d${i}`}>What we see</label>
            <textarea
              id={`d${i}`}
              rows={3}
              className={cls(`scenes.${i}.description`)}
              value={s.description}
              onChange={editScene(i, 'description')}
              maxLength={500}
            />
            <label htmlFor={`v${i}`}>Voiceover</label>
            <input
              id={`v${i}`}
              className={cls(`scenes.${i}.voiceover`)}
              value={s.voiceover}
              onChange={editScene(i, 'voiceover')}
              maxLength={220}
            />
            <label htmlFor={`t${i}`}>On-screen text</label>
            <input
              id={`t${i}`}
              className={cls(`scenes.${i}.on_screen_text`)}
              value={s.on_screen_text}
              onChange={editScene(i, 'on_screen_text')}
              maxLength={80}
            />
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
          {board.hooks.map((h, i) => (
            <li key={h.formula} className="hook-edit">
              <label htmlFor={`h${i}`} className="pill">
                {FORMULA_LABEL[h.formula]}
              </label>
              <input id={`h${i}`} className={cls(`hooks.${i}.text`)} value={h.text} onChange={editHook(i)} maxLength={160} />
            </li>
          ))}
        </ul>
        <p className="muted small">
          The ad opens with the first hook. Hook Lab, which renders and ranks all three, arrives in a later version.
        </p>
      </section>

      <div className="actions">
        {error && <p className="error" role="alert">{error}</p>}
        <p className="muted small">
          Approving renders {scenesN === 1 ? 'scene 1' : `${scenesN} scenes`} (a reference image and a 5-second clip
          each)
          {config && <> for about {formatMoney(config.job_estimate, currency)}</>}, under a cap of{' '}
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
  const [scenesN, setScenesN] = useState(null);
  useEffect(() => {
    api.config().then(
      (c) => setScenesN(c.render_scenes),
      () => setScenesN(3),
    );
  }, []);
  const rendered = Math.max(0, ...job.stages.filter((s) => s.scene_idx >= 0).map((s) => s.scene_idx + 1));
  const n = Math.max(scenesN ?? 1, rendered);
  const sceneMedia = Array.from({ length: n }, (_, i) => ({
    idx: i,
    video: job.assets.find((a) => a.kind === 'video' && a.scene_idx === i),
    image: job.assets.find((a) => a.kind === 'image' && a.scene_idx === i),
  }));
  const expected = [
    { stage: 'analyze', scene_idx: -1 },
    { stage: 'storyboard', scene_idx: -1 },
    ...sceneMedia.flatMap(({ idx }) => [
      { stage: 'image', scene_idx: idx },
      { stage: 'video', scene_idx: idx },
    ]),
  ];
  const stageStatus = (st) =>
    job.stages.find((s) => s.stage === st.stage && s.scene_idx === st.scene_idx) || { status: 'waiting' };
  const active = job.status === 'queued' || job.status === 'running';
  const ratioClass = `ratio-${job.brief.aspect_ratio.replace(':', 'x')}`;

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
                <li key={`${st.stage}-${st.scene_idx}`}>
                  <StageIcon status={s.status} />
                  <span>
                    {STAGE_LABEL[st.stage]}
                    {st.scene_idx >= 0 ? ` (scene ${st.scene_idx + 1})` : ''}
                  </span>
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
          <div className={`scene-clips n${n}`}>
            {sceneMedia.map(({ idx, video, image }) => (
              <figure key={idx}>
                {video ? (
                  <video src={video.url} controls playsInline poster={image?.url} className={ratioClass} />
                ) : image ? (
                  <img src={image.url} alt={`Reference image for scene ${idx + 1}`} className={ratioClass} />
                ) : (
                  <div className="placeholder">
                    <Loader2 className={active ? 'spin' : ''} size={24} aria-hidden="true" />
                    <span className="muted small">{active ? 'Rendering…' : 'No media yet'}</span>
                  </div>
                )}
                {n > 1 && <figcaption className="muted small">Scene {idx + 1}</figcaption>}
              </figure>
            ))}
          </div>
          {job.status === 'done' && (
            <p className="ok small">
              Done.{' '}
              {n > 1 ? 'The next version joins the scenes into one ad with voiceover, captions and music. ' : ''}
              Links to the files expire after a few minutes; reload to refresh them.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

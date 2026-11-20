import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Circle, Clapperboard, Film, Loader2, RotateCcw, Upload, XCircle } from 'lucide-react';
import { api, rememberJob } from '../lib/api';
import { navigate, useCurrency } from '../lib/hooks';
import { formatMoney } from '../lib/money';
import { Help } from '../components/Help';
import { HELP } from '../lib/help';
import Stepper, { BackButton } from '../components/Stepper';
import { goToBrief } from '../lib/steps';

const POLL_MS = 3000;
const ROLE_LABEL = { hook: 'Scene 1 · Hook', demo: 'Scene 2 · Demo', cta: 'Scene 3 · Call to action' };
const FORMULA_LABEL = {
  pov: 'POV',
  problem_first: 'Problem first',
  three_reasons: '3 reasons',
  unboxing_tease: 'Unboxing tease',
};
const SOURCE_LABEL = { generate: 'Generate', product: 'My product photo', upload: 'Upload my own' };

const isActive = (j) => j.status === 'queued' || j.status === 'running';
const ZERO = { usd: 0, eur: 0 };
const add = (a, b, k = 1) => ({ usd: a.usd + b.usd * k, eur: a.eur + b.eur * k });

// Live estimate from the server's unit prices (own images are free; clips by their length).
function estimateBoard(board, prices, n = 3) {
  let images = ZERO;
  let video = ZERO;
  if (!board || !prices) return null;
  board.scenes.slice(0, n).forEach((s) => {
    if (s.image_source === 'generate') images = add(images, prices.image);
    video = add(video, prices.video_per_second, s.duration_s);
    if (s.voiceover.trim()) video = add(video, prices.voice_line);
  });
  return { images, video, total: add(images, video) };
}

function useConfig() {
  const [config, setConfig] = useState(null);
  useEffect(() => {
    api.config().then(setConfig, () => {});
  }, []);
  return config;
}

export default function Job({ jobId, view }) {
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
  const imagesDone = job.status === 'done' || job.phase === 'video';
  if (view === 'storyboard' || job.status === 'draft') {
    return <StoryboardStep key={job.status} job={job} onChange={update} readOnly={job.status !== 'draft'} />;
  }
  if (job.phase === 'images' && view !== 'video') {
    return imagesDone ? <ImagesStep key={job.phase} job={job} onChange={update} /> : <GenerateStep job={job} onChange={update} />;
  }
  if (view === 'images') return <ImagesStep key={job.phase} job={job} onChange={update} readOnly />;
  return <GenerateStep job={job} onChange={update} />;
}

// --- shared bits ---------------------------------------------------------------------------
function Choice({ name, value, checked, onChange, title, children, disabled }) {
  return (
    <label className={`choice${checked ? ' selected' : ''}`}>
      <input type="radio" name={name} value={value} checked={checked} onChange={onChange} disabled={disabled} />
      <span className="choice-body">
        <span className="choice-title">{title}</span>
        {children}
      </span>
    </label>
  );
}

function Chip({ name, value, checked, onChange, children, disabled }) {
  return (
    <label className={`chip${checked ? ' selected' : ''}`}>
      <input type="radio" name={name} value={value} checked={checked} onChange={onChange} disabled={disabled} />
      {children}
    </label>
  );
}

function CostBox({ rows, spend, cap, currency }) {
  const total = rows.reduce((acc, [, m]) => add(acc, m), ZERO);
  const over = spend.eur + total.eur > cap.eur + 1e-9;
  return (
    <div className="cost-box" aria-live="polite">
      {rows.map(([label, m]) => (
        <div className="row" key={label}>
          <span>{label}</span>
          <strong>{formatMoney(m, currency)}</strong>
        </div>
      ))}
      <div className="row muted small">
        <span>Spent so far on this ad</span>
        <span>{formatMoney(spend, currency)}</span>
      </div>
      <div className={`row small ${over ? 'over' : 'muted'}`}>
        <span>Cap per ad</span>
        <span>
          {formatMoney(cap, currency)}
          {over ? ' (over the cap: use 5 s clips or your own images)' : ''}
        </span>
      </div>
    </div>
  );
}

function FieldLabel({ htmlFor, text, help }) {
  return (
    <label htmlFor={htmlFor}>
      {text}
      {help && <Help text={help} />}
    </label>
  );
}

// --- step 2: storyboard ----------------------------------------------------------------------
function StoryboardStep({ job, onChange, readOnly }) {
  const currency = useCurrency();
  const config = useConfig();
  const [board, setBoard] = useState(job.storyboard);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [showPrompts, setShowPrompts] = useState(true);
  const [storyMode, setStoryMode] = useState(job.brief.story ? 'own' : 'ai');
  const [story, setStory] = useState(job.brief.story || '');
  const [writtenLine] = useState(job.storyboard?.scenes[0]?.voiceover || '');
  const [hookMode, setHookMode] = useState(
    job.storyboard?.hook_choice != null ? `h${job.storyboard.hook_choice}` : 'written',
  );
  const [ownHook, setOwnHook] = useState('');
  const n = config?.render_scenes ?? 3;
  const estimate = useMemo(() => estimateBoard(board, config?.prices, n), [board, config, n]);

  if (!board) {
    return (
      <div className="page">
        <Stepper step={2} job={job} />
        <div className="card narrow">
          <h2>No storyboard yet</h2>
          <p className="error" role="alert">{job.last_error || 'The storyboard could not be written.'}</p>
          <button className="btn btn-primary" onClick={() => goToBrief(job)}>Back to the brief</button>
        </div>
      </div>
    );
  }

  const flags = job.flags || [];
  const cls = (field) => (flags.some((f) => f.field === field) ? 'flagged' : undefined);
  const change = (next) => {
    setBoard(next);
    setDirty(true);
  };
  const editScene = (i, field, value) =>
    change({ ...board, scenes: board.scenes.map((s, j) => (j === i ? { ...s, [field]: value } : s)) });
  const onScene = (i, field) => (e) => editScene(i, field, e.target.value);
  const editTop = (field) => (e) => change({ ...board, [field]: e.target.value });

  function pickHook(mode, text) {
    setHookMode(mode);
    const line = mode === 'written' ? writtenLine : text;
    const choice = mode.startsWith('h') ? Number(mode.slice(1)) : null;
    change({
      ...board,
      hook_choice: choice,
      scenes: board.scenes.map((s, j) => (j === 0 ? { ...s, voiceover: line } : s)),
    });
  }
  const editHookText = (i) => (e) => {
    const hooks = board.hooks.map((h, j) => (j === i ? { ...h, text: e.target.value } : h));
    const next = { ...board, hooks };
    if (hookMode === `h${i}`) next.scenes = board.scenes.map((s, j) => (j === 0 ? { ...s, voiceover: e.target.value } : s));
    change(next);
  };

  async function run(label, fn) {
    setBusy(label);
    setError('');
    try {
      return await fn();
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setBusy('');
    }
  }

  async function save() {
    const saved = await api.saveStoryboard(job.id, board);
    setDirty(false);
    onChange(saved);
    return saved;
  }

  const buildFromStory = () =>
    run('story', async () => {
      const view = await api.story(job.id, story.trim());
      setBoard(view.storyboard);
      setDirty(false);
      setHookMode('written');
      onChange(view);
    });

  const uploadFor = (i) => async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    await run(`upload${i}`, async () => {
      if (dirty) await save();
      const view = await api.uploadSceneImage(job.id, i, file);
      setBoard(view.storyboard);
      setDirty(false);
      onChange(view);
    });
  };

  const approve = () =>
    run('approve', async () => {
      const current = dirty ? await save() : job;
      if ((current.flags || []).length) {
        setError('Some lines still need editing (marked in red).');
        return;
      }
      onChange(await api.approve(job.id));
      navigate(`/job/${job.id}`);
    });

  const check = () => run('check', save);
  const uploads = (i) => job.assets.filter((a) => a.kind === 'upload' && a.scene_idx === i);
  const disabled = readOnly || Boolean(busy);

  return (
    <div className="page">
      <Stepper step={2} job={job} />
      <BackButton onClick={() => goToBrief(job)}>Back to the brief</BackButton>
      <div className="row between">
        <h1>{board.title}</h1>
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setShowPrompts(!showPrompts)} aria-expanded={showPrompts}>
          {showPrompts ? 'Hide' : 'Show'} image and motion prompts
        </button>
      </div>
      <p className="muted">
        {readOnly
          ? 'Approved: the storyboard is locked. On the Images step you can still edit the voiceover, text, motion and clip length before the video is made.'
          : 'Choose where the story comes from, check each scene, pick the opening hook, then approve. Nothing is rendered before you approve.'}
      </p>

      <section className="card">
        <h2>
          Story <Help text={HELP.story} />
        </h2>
        <div className="choice-group" role="radiogroup" aria-label="Where the story comes from">
          <Choice name="story" value="ai" checked={storyMode === 'ai'} onChange={() => setStoryMode('ai')} disabled={disabled} title="AI storyboard from my brief">
            <span className="muted small">The scenes below, written from your brief.</span>
          </Choice>
          <Choice name="story" value="own" checked={storyMode === 'own'} onChange={() => setStoryMode('own')} disabled={disabled} title="My own story">
            <span className="muted small">
              Paste your story or script. Your spoken lines are kept word for word; the scenes, prompts and hook ideas follow it (a few cents).
            </span>
            {storyMode === 'own' && (
              <>
                <textarea
                  rows={5}
                  value={story}
                  onChange={(e) => setStory(e.target.value)}
                  maxLength={4000}
                  placeholder="For example: My grandad played every Sunday in boots that slipped. Now the whole team wears…"
                  disabled={disabled}
                  aria-label="Your story"
                />
                <div>
                  <button type="button" className="btn btn-secondary btn-small" onClick={buildFromStory} disabled={disabled || story.trim().length < 20}>
                    {busy === 'story' ? (
                      <>
                        <Loader2 className="spin" size={14} aria-hidden="true" /> Writing the scenes…
                      </>
                    ) : (
                      'Build the scenes from my story'
                    )}
                  </button>
                  {dirty && <span className="muted small"> Replaces the scenes below, including unsaved edits.</span>}
                </div>
              </>
            )}
          </Choice>
        </div>
      </section>

      {flags.length > 0 && (
        <div className="notice flag-notice" role="status">
          <AlertTriangle size={16} aria-hidden="true" />
          <div>
            <strong>
              {flags.length} {flags.length === 1 ? 'line needs' : 'lines need'} editing before you approve.
            </strong>{' '}
            An ad may only claim use, results, reviews or awards that your brief or story states. Rewrite the marked lines, then check again.
            <ul>
              {flags.map((f) => (
                <li key={f.field + f.text}>
                  “{f.text}” <span className="muted">({f.reason})</span>
                </li>
              ))}
            </ul>
            <button type="button" className="btn btn-secondary btn-small" onClick={check} disabled={disabled}>
              Check again
            </button>
          </div>
        </div>
      )}

      <section className="card">
        <div className="grid-2 tight">
          <div>
            <FieldLabel htmlFor="title" text="Title" help={HELP.title} />
            <input id="title" className={cls('title')} value={board.title} onChange={editTop('title')} maxLength={100} disabled={disabled} />
          </div>
          <div>
            <FieldLabel htmlFor="cta" text="Call to action (button)" help={HELP.cta_text} />
            <input id="cta" className={cls('cta_text')} value={board.cta_text} onChange={editTop('cta_text')} maxLength={60} disabled={disabled} />
          </div>
        </div>
      </section>

      <div className="scenes">
        {board.scenes.slice(0, n).map((s, i) => {
          const own = uploads(i).at(-1);
          return (
            <article key={s.role} className="card scene">
              <h2>
                {ROLE_LABEL[s.role]} <Help text={HELP[s.role]} />
              </h2>
              <FieldLabel htmlFor={`d${i}`} text="What we see" help={HELP.description} />
              <textarea id={`d${i}`} rows={3} className={cls(`scenes.${i}.description`)} value={s.description} onChange={onScene(i, 'description')} maxLength={800} disabled={disabled} />
              <FieldLabel htmlFor={`v${i}`} text="Voiceover" help={HELP.voiceover} />
              <input id={`v${i}`} className={cls(`scenes.${i}.voiceover`)} value={s.voiceover} onChange={onScene(i, 'voiceover')} maxLength={220} disabled={disabled} />
              <FieldLabel htmlFor={`t${i}`} text="On-screen text" help={HELP.on_screen_text} />
              <input id={`t${i}`} className={cls(`scenes.${i}.on_screen_text`)} value={s.on_screen_text} onChange={onScene(i, 'on_screen_text')} maxLength={80} disabled={disabled} />

              <span className="label-like">
                Image <Help text={HELP.image_source} />
              </span>
              <div className="choice-row stack" role="radiogroup" aria-label={`Image for scene ${i + 1}`}>
                {['generate', 'product', 'upload'].map((src) => (
                  <Chip key={src} name={`src${i}`} value={src} checked={s.image_source === src} disabled={disabled || (src === 'upload' && !own)} onChange={() => editScene(i, 'image_source', src)}>
                    {SOURCE_LABEL[src]}
                    {config && <span className="muted small">{src === 'generate' ? formatMoney(config.prices.image, currency) : 'free'}</span>}
                  </Chip>
                ))}
              </div>
              {!readOnly && (
                <label className="btn btn-ghost btn-small upload-btn">
                  {busy === `upload${i}` ? <Loader2 className="spin" size={14} aria-hidden="true" /> : <Upload size={14} aria-hidden="true" />} Upload an image for this scene
                  <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={uploadFor(i)} disabled={disabled} />
                </label>
              )}
              {s.image_source === 'upload' && own && <img className="scene-image" src={own.url} alt={`Your image for scene ${i + 1}`} />}

              <div className="field-row">
                <span className="label-like">
                  Clip length <Help text={HELP.clip} />
                </span>
                <div className="choice-row" role="radiogroup" aria-label={`Clip length for scene ${i + 1}`}>
                  {[5, 10].map((sec) => (
                    <Chip key={sec} name={`dur${i}`} value={sec} checked={s.duration_s === sec} onChange={() => editScene(i, 'duration_s', sec)} disabled={disabled}>
                      {sec} s
                      {config && (
                        <span className="muted small">
                          {formatMoney({ usd: config.prices.video_per_second.usd * sec, eur: config.prices.video_per_second.eur * sec }, currency)}
                        </span>
                      )}
                    </Chip>
                  ))}
                </div>
              </div>

              {showPrompts && (
                <>
                  <FieldLabel htmlFor={`ip${i}`} text="Image prompt" help={HELP.image_prompt} />
                  <textarea id={`ip${i}`} rows={7} value={s.image_prompt} onChange={onScene(i, 'image_prompt')} maxLength={2500} disabled={disabled || s.image_source !== 'generate'} />
                  {s.image_source !== 'generate' && <p className="muted small">Not used: this scene uses your own image.</p>}
                  <FieldLabel htmlFor={`mp${i}`} text="Motion prompt (shot list)" help={HELP.motion_prompt} />
                  <textarea id={`mp${i}`} rows={7} value={s.motion_prompt} onChange={onScene(i, 'motion_prompt')} maxLength={2200} disabled={disabled} />
                </>
              )}
            </article>
          );
        })}
      </div>

      <section className="card">
        <h2>
          Opening hook for scene 1 <Help text={HELP.hooks} />
        </h2>
        <div className="choice-group" role="radiogroup" aria-label="Opening hook">
          <Choice name="hook" value="written" checked={hookMode === 'written'} onChange={() => pickHook('written')} disabled={disabled} title="Keep scene 1 as written">
            <span className="muted small">“{writtenLine}”</span>
          </Choice>
          {board.hooks.map((h, i) => (
            <Choice
              key={h.formula}
              name="hook"
              value={`h${i}`}
              checked={hookMode === `h${i}`}
              onChange={() => pickHook(`h${i}`, h.text)}
              disabled={disabled}
              title={
                <>
                  {FORMULA_LABEL[h.formula]} <Help text={HELP[h.formula]} />
                </>
              }
            >
              <input type="text" className={cls(`hooks.${i}.text`)} value={h.text} onChange={editHookText(i)} maxLength={160} disabled={disabled} aria-label={`${FORMULA_LABEL[h.formula]} hook`} />
            </Choice>
          ))}
          <Choice name="hook" value="own" checked={hookMode === 'own'} onChange={() => pickHook('own', ownHook)} disabled={disabled} title="My own hook">
            <input
              type="text"
              value={ownHook}
              placeholder="Write the first line people hear"
              maxLength={160}
              disabled={disabled}
              aria-label="Your own hook"
              onChange={(e) => {
                setOwnHook(e.target.value);
                if (hookMode === 'own') editScene(0, 'voiceover', e.target.value);
              }}
            />
          </Choice>
        </div>
        <p className="muted small">The ticked hook becomes scene 1&rsquo;s voiceover. Hook Lab, which renders and ranks all three, arrives in a later version.</p>
      </section>

      {!readOnly && (
        <div className="actions">
          {estimate && (
            <CostBox
              rows={[
                ['Step 1, images (now)', estimate.images],
                ['Step 2, video and voice (later, your choice)', estimate.video],
              ]}
              spend={job.spend}
              cap={job.cost_cap}
              currency={currency}
            />
          )}
          {error && <p className="error" role="alert">{error}</p>}
          <p className="muted small">
            Approving makes the images only <Help text={HELP.approve_images} />. You see them, can still change the voiceover, text, motion and clip lengths, and then decide whether to make the video.
          </p>
          <button className="btn btn-primary" onClick={approve} disabled={disabled}>
            {busy === 'approve' ? 'Approving…' : `Approve and make the images${estimate ? ` (${formatMoney(estimate.images, currency)})` : ''}`}
          </button>
        </div>
      )}
      {readOnly && (
        <div className="actions">
          <button className="btn btn-secondary" onClick={() => navigate(`/job/${job.id}/images`)}>Go to the images →</button>
        </div>
      )}
    </div>
  );
}

// --- step 3: images ---------------------------------------------------------------------------
function ImagesStep({ job, onChange, readOnly = false }) {
  const currency = useCurrency();
  const config = useConfig();
  const [board, setBoard] = useState(job.storyboard);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const n = config?.render_scenes ?? 3;
  const estimate = useMemo(() => estimateBoard(board, config?.prices, n), [board, config, n]);
  const locked = readOnly || job.phase === 'video';
  const editScene = (i, field, value) =>
    setBoard({ ...board, scenes: board.scenes.map((s, j) => (j === i ? { ...s, [field]: value } : s)) });

  async function makeVideo() {
    setBusy(true);
    setError('');
    try {
      const view = await api.makeVideo(job.id, board);
      onChange(view);
      navigate(`/job/${job.id}/video`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Stepper step={3} job={job} />
      <BackButton onClick={() => navigate(`/job/${job.id}/storyboard`)}>Back to the storyboard</BackButton>
      <h1>Your images</h1>
      <p className="muted">
        {locked
          ? 'These images were used for the video.'
          : 'Check the pictures. You can still change each scene’s voiceover, text, motion and clip length. Then make the video, or keep the images only.'}
      </p>
      <div className="scenes">
        {board.scenes.slice(0, n).map((s, i) => {
          const image = job.assets.find((a) => a.kind === 'image' && a.scene_idx === i);
          return (
            <article key={s.role} className="card scene">
              <h2>
                {ROLE_LABEL[s.role]} <Help text={HELP[s.role]} />
              </h2>
              {image ? (
                <a href={image.url} target="_blank" rel="noreferrer">
                  <img className="scene-image" src={image.url} alt={`Scene ${i + 1}`} />
                </a>
              ) : (
                <p className="muted small">No image.</p>
              )}
              <p className="muted small">
                {s.image_source === 'generate' ? 'Generated' : s.image_source === 'product' ? 'Your product photo' : 'Your own image'}
              </p>
              <FieldLabel htmlFor={`iv${i}`} text="Voiceover" help={HELP.voiceover} />
              <input id={`iv${i}`} value={s.voiceover} onChange={(e) => editScene(i, 'voiceover', e.target.value)} maxLength={220} disabled={locked} />
              <FieldLabel htmlFor={`it${i}`} text="On-screen text" help={HELP.on_screen_text} />
              <input id={`it${i}`} value={s.on_screen_text} onChange={(e) => editScene(i, 'on_screen_text', e.target.value)} maxLength={80} disabled={locked} />
              <div className="field-row">
                <span className="label-like">
                  Clip length <Help text={HELP.clip} />
                </span>
                <div className="choice-row" role="radiogroup" aria-label={`Clip length for scene ${i + 1}`}>
                  {[5, 10].map((sec) => (
                    <Chip key={sec} name={`idur${i}`} value={sec} checked={s.duration_s === sec} onChange={() => editScene(i, 'duration_s', sec)} disabled={locked}>
                      {sec} s
                    </Chip>
                  ))}
                </div>
              </div>
              <FieldLabel htmlFor={`imp${i}`} text="Motion prompt (shot list)" help={HELP.motion_prompt} />
              <textarea id={`imp${i}`} rows={8} value={s.motion_prompt} onChange={(e) => editScene(i, 'motion_prompt', e.target.value)} maxLength={2200} disabled={locked} />
            </article>
          );
        })}
      </div>
      {!locked && (
        <div className="actions">
          {estimate && <CostBox rows={[['Step 2, video and voice', estimate.video]]} spend={job.spend} cap={job.cost_cap} currency={currency} />}
          {error && <p className="error" role="alert">{error}</p>}
          <p className="muted small">
            Making the video adds the voiceover, one clip per scene, captions, music and the end card, in every format <Help text={HELP.make_video} />. You can close the tab while it runs.
          </p>
          <button className="btn btn-primary" onClick={makeVideo} disabled={busy}>
            <Film size={16} aria-hidden="true" /> {busy ? 'Starting…' : `Make the video${estimate ? ` (${formatMoney(estimate.video, currency)})` : ''}`}
          </button>
          <p className="muted small">Happy with the images only? Open each one and save it; nothing more is charged.</p>
        </div>
      )}
      {locked && (
        <div className="actions">
          <button className="btn btn-secondary" onClick={() => navigate(`/job/${job.id}/video`)}>Go to the video →</button>
        </div>
      )}
    </div>
  );
}

// --- progress and the finished ad -----------------------------------------------------------------
const STAGE_LABEL = {
  analyze: 'Read the product photo',
  storyboard: 'Write the storyboard',
  voice: 'Voiceover',
  image: 'Image',
  video: 'Video clip',
  compose: 'Edit the ad: captions, music, end card, every format',
};

const RATIO_LABEL = { '9:16': '9:16 vertical', '1:1': '1:1 square', '4:5': '4:5 portrait', '16:9': '16:9 landscape' };

function StageIcon({ status }) {
  if (status === 'done') return <CheckCircle2 size={18} className="ok" aria-label="done" />;
  if (status === 'failed') return <XCircle size={18} className="bad" aria-label="failed" />;
  if (status === 'running' || status === 'submitted') return <Loader2 size={18} className="spin" aria-label="in progress" />;
  return <Circle size={18} className="muted" aria-label="waiting" />;
}

function FinishedAd({ job, variant }) {
  const ads = job.assets.filter((a) => a.kind === 'ad');
  const ordered = variant.ratios.map((r) => ads.find((a) => a.ratio === r)).filter(Boolean);
  const [ratio, setRatio] = useState(ordered[0]?.ratio);
  const current = ordered.find((a) => a.ratio === ratio) || ordered[0];
  const cover = job.assets.find((a) => a.kind === 'cover');
  const stills = job.assets.filter((a) => a.kind === 'still');
  const carousel = job.assets.filter((a) => a.kind === 'carousel');
  if (!current) return null;
  return (
    <div className="finished">
      <div className="ratio-tabs" role="tablist" aria-label="Format">
        {ordered.map((a) => (
          <button
            key={a.ratio}
            type="button"
            role="tab"
            aria-selected={a.ratio === current.ratio}
            className={a.ratio === current.ratio ? 'tab active' : 'tab'}
            onClick={() => setRatio(a.ratio)}
          >
            {RATIO_LABEL[a.ratio] || a.ratio}
          </button>
        ))}
      </div>
      <video key={current.url} src={current.url} controls playsInline poster={cover?.url} className={`ratio-${current.ratio.replace(':', 'x')}`} />
      <p className="small">
        <a href={current.url} download={current.name} target="_blank" rel="noreferrer">
          Open {RATIO_LABEL[current.ratio] || current.ratio} ({variant.duration_s?.toFixed(1)} s)
        </a>{' '}
        <span className="muted">(right-click the video to save it)</span>
      </p>
      {Object.keys(variant.skipped || {}).length > 0 && (
        <p className="muted small">
          Not exported:{' '}
          {Object.entries(variant.skipped)
            .map(([r, why]) => `${r} (${why})`)
            .join('; ')}
          .
        </p>
      )}
      {(stills.length > 0 || carousel.length > 0) && (
        <div className="extras">
          <h3>Images</h3>
          <div className="thumbs">
            {[cover, ...stills, ...carousel].filter(Boolean).map((a) => (
              <a key={a.name} href={a.url} target="_blank" rel="noreferrer" title={a.name}>
                <img src={a.url} alt={a.name} />
              </a>
            ))}
          </div>
          <p className="muted small">Cover, one still per scene, and a 4:5 carousel ending on the call to action.</p>
        </div>
      )}
      <p className="muted small">
        Every file is marked as AI-generated in its metadata. When you post, turn on the platform&rsquo;s AI-generated label: the images, video and voice are made by AI.
      </p>
    </div>
  );
}

function GenerateStep({ job, onChange }) {
  const currency = useCurrency();
  const config = useConfig();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const n = Math.max(config?.render_scenes ?? 1, ...job.stages.filter((s) => s.scene_idx >= 0).map((s) => s.scene_idx + 1));
  const idxs = Array.from({ length: n }, (_, i) => i);
  const videoPhase = job.phase === 'video';
  const expected = [
    { stage: 'analyze', scene_idx: -1 },
    { stage: 'storyboard', scene_idx: -1 },
    ...idxs.map((i) => ({ stage: 'image', scene_idx: i })),
    ...(videoPhase
      ? [
          ...idxs.filter((i) => job.storyboard?.scenes[i]?.voiceover).map((i) => ({ stage: 'voice', scene_idx: i })),
          ...idxs.map((i) => ({ stage: 'video', scene_idx: i })),
          { stage: 'compose', scene_idx: -1 },
        ]
      : []),
  ];
  const stageStatus = (st) => job.stages.find((s) => s.stage === st.stage && s.scene_idx === st.scene_idx) || { status: 'waiting' };
  const active = isActive(job);
  const ratioClass = `ratio-${job.brief.aspect_ratio.replace(':', 'x')}`;
  const variant = job.variants?.find((v) => v.label === 'A');
  const finished = videoPhase && variant && variant.ratios?.length > 0 && job.assets.some((a) => a.kind === 'ad');

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
      <Stepper step={videoPhase ? 4 : 3} job={job} />
      <BackButton onClick={() => navigate(`/job/${job.id}/${videoPhase ? 'images' : 'storyboard'}`)}>
        Back to the {videoPhase ? 'images' : 'storyboard'}
      </BackButton>
      <h1>
        {videoPhase && <Clapperboard size={26} aria-hidden="true" />} {videoPhase ? 'Your video' : 'Making the images'}
      </h1>
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
          {active && <p className="muted small">You can close this tab: it continues on the server. Come back to this page in this browser to see the result.</p>}
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
          {finished ? (
            <FinishedAd job={job} variant={variant} />
          ) : (
            <div className={`scene-clips n${n}`}>
              {idxs.map((idx) => {
                const video = job.assets.find((a) => a.kind === 'video' && a.scene_idx === idx);
                const image = job.assets.find((a) => a.kind === 'image' && a.scene_idx === idx);
                return (
                  <figure key={idx}>
                    {video ? (
                      <video src={video.url} controls playsInline poster={image?.url} className={ratioClass} />
                    ) : image ? (
                      <img src={image.url} alt={`Scene ${idx + 1}`} className={ratioClass} />
                    ) : (
                      <div className="placeholder">
                        <Loader2 className={active ? 'spin' : ''} size={24} aria-hidden="true" />
                        <span className="muted small">{active ? 'Rendering…' : 'No media yet'}</span>
                      </div>
                    )}
                    {n > 1 && <figcaption className="muted small">Scene {idx + 1}</figcaption>}
                  </figure>
                );
              })}
            </div>
          )}
          {job.status === 'done' && <p className="ok small">Done. Links to the files expire after a few minutes; reload to refresh them.</p>}
        </section>
      </div>
    </div>
  );
}

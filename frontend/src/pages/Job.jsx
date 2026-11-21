import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Circle, Clapperboard, Film, Loader2, RotateCcw, Sparkles, Upload, XCircle } from 'lucide-react';
import { api, rememberJob } from '../lib/api';
import { navigate, useCurrency } from '../lib/hooks';
import { formatMoney } from '../lib/money';
import { Help } from '../components/Help';
import { HELP } from '../lib/help';
import Stepper, { BackButton } from '../components/Stepper';
import AutoTextarea from '../components/AutoTextarea';
import SoundCard from '../components/SoundCard';
import CharCount, { STORY_MAX } from '../components/CharCount';
import { ClipExact, ClipTooLong } from '../components/ClipFit';
import { useClipTexts } from '../lib/clips';
import { KIND_LABEL, modelLabel } from '../lib/models';
import { goToBrief } from '../lib/steps';

const POLL_MS = 3000;
const ROLE_NAME = { hook: 'Hook', demo: 'Demo', cta: 'Call to action' };
const sceneTitle = (s, i) => `Scene ${i + 1} · ${ROLE_NAME[s.role] || s.role}`;
const MAX_SCENES = 5;
const rolesFor = (n) => (n === 1 ? ['cta'] : ['hook', ...Array(n - 2).fill('demo'), 'cta']);
const FORMULA_LABEL = {
  pov: 'POV',
  problem_first: 'Problem first',
  three_reasons: '3 reasons',
  unboxing_tease: 'Unboxing tease',
};
// The three hook ideas, said plainly.
const HOOK_KIND = {
  pov: 'put the viewer in the moment',
  problem_first: 'start with a problem they know',
  three_reasons: 'promise a quick list',
  unboxing_tease: 'build curiosity',
};
const HOOK_HOW = {
  pov: 'Talks as if it is happening to them, often starting with "POV:".',
  problem_first: 'Names something annoying they know, then your product is the fix.',
  three_reasons: 'Promises a few quick reasons, so they stay to hear them.',
  unboxing_tease: 'Reveals the product bit by bit, so they wait for the rest.',
};
const SOURCE_LABEL = { generate: 'Generate', product: 'My product photo', upload: 'Upload my own' };

const isActive = (j) => j.status === 'queued' || j.status === 'running';
const ZERO = { usd: 0, eur: 0 };
const add = (a, b, k = 1) => ({ usd: a.usd + b.usd * k, eur: a.eur + b.eur * k });
const MIN_SCENE_S = 2;
const MAX_SCENE_S = 10;
const renderSeconds = (d) => (d <= 5 ? 5 : 10); // the video model makes 5 s or 10 s clips; shorter scenes are cut
const clampScene = (v) => Math.max(MIN_SCENE_S, Math.min(MAX_SCENE_S, Math.round(Number(v) || MIN_SCENE_S)));

// Split a total ad length over the scenes (each 2-10 s).
function splitLength(total, n) {
  const t = Math.max(MIN_SCENE_S * n, Math.min(MAX_SCENE_S * n, Math.round(total)));
  const base = Math.floor(t / n);
  return Array.from({ length: n }, (_, i) => clampScene(base + (i < t - base * n ? 1 : 0)));
}

// Live estimate from the server's unit prices (own images are free; clips by their length).
// A scene after the first, in a continuous shot, without a picture of its own, starts from the
// previous scene's last frame (no new picture).
const isChained = (board, i, s) => board?.continuity === 'continuous' && i > 0 && s.image_source === 'generate';
// D30: in a connected video, a scene with its own picture is reached by the clip before it,
// which ends on that picture.
const endsOnNext = (board, i) => {
  const next = board?.scenes?.[i + 1];
  return board?.continuity === 'continuous' && Boolean(next) && next.image_source !== 'generate';
};

function estimateBoard(board, prices, n = 3, voice = 'marin') {
  let images = ZERO;
  let video = ZERO;
  if (!board || !prices) return null;
  board.scenes.slice(0, n).forEach((s, i) => {
    if (s.image_source === 'generate' && !isChained(board, i, s)) images = add(images, prices.image);
    video = add(video, prices.video_per_second, renderSeconds(s.duration_s));
    if (s.voiceover.trim() && voice !== 'none') video = add(video, prices.voice_line);
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

// What each scene's clip starts from, said plainly (the video AI animates one picture per scene).
function pictureNote(scenes, board) {
  const chained = scenes.filter((s, i) => isChained(board, i, s)).length;
  const count = (src) => scenes.filter((s, i) => s.image_source === src && !isChained(board, i, s)).length;
  const [gen, product, own] = [count('generate'), count('product'), count('upload')];
  const word = (k) => (k === 1 ? 'scene' : 'scenes');
  const parts = [];
  if (gen) parts.push(`${gen === scenes.length ? 'Every scene' : `${gen} ${word(gen)}`} ${gen === 1 && gen !== scenes.length ? 'gets' : 'get'} a new picture made from your product photo, showing your product in that scene's setting`);
  if (product)
    parts.push(
      product === scenes.length
        ? `all ${product} ${word(product)} start from your same product photo: each clip animates that photo differently, and no new pictures are made`
        : `${product} ${word(product)} ${product === 1 ? 'starts' : 'start'} from your product photo itself`,
    );
  if (own) parts.push(`${own} ${word(own)} ${own === 1 ? 'starts' : 'start'} from the picture you uploaded for ${own === 1 ? 'it' : 'them'}`);
  if (chained) parts.push(`${chained} ${word(chained)} ${chained === 1 ? 'continues' : 'continue'} from where the previous scene ends (no new picture)`);
  const text = parts.join('; ');
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}. The video AI animates one picture per scene.`.replace('Every scene get ', 'Every scene gets ');
}

function CostBox({ rows, spend, cap, currency, total: shownTotal = null, note = '' }) {
  const total = rows.reduce((acc, [, m]) => add(acc, m), ZERO);
  const over = spend.eur + total.eur > cap.eur + 1e-9;
  return (
    <div className="cost-box" aria-live="polite">
      {rows.map(([label, m]) => (
        <div className="row" key={label}>
          <span>{label}</span>
          <span>{formatMoney(m, currency)}</span>
        </div>
      ))}
      {shownTotal && (
        <div className="row total">
          <strong>Total</strong>
          <strong>{formatMoney(shownTotal, currency)}</strong>
        </div>
      )}
      {note && <p className="muted small">{note}</p>}
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

function SceneLength({ id, value, onChange, disabled, prices, currency, endsOnNext: fitsNext = false }) {
  return (
    <div className="field-row">
      <label htmlFor={id} className="label-like">
        Length <Help text={HELP.clip} />
      </label>
      <span className="length-input">
        <input
          id={id}
          type="number"
          min={MIN_SCENE_S}
          max={MAX_SCENE_S}
          step={1}
          value={value}
          onChange={(e) => onChange(clampScene(e.target.value))}
          disabled={disabled}
        />{' '}
        s
      </span>
      {prices && (
        <span className="muted small length-note">
          This scene: the AI makes a {renderSeconds(value)} s clip
          {value < renderSeconds(value)
            ? fitsNext
              ? `, played a little faster in ${value} s so it ends on the next picture`
              : ` and the first ${value} s are used`
            : ''}{' '}
          ·{' '}
          {formatMoney(
            { usd: prices.video_per_second.usd * renderSeconds(value), eur: prices.video_per_second.eur * renderSeconds(value) },
            currency,
          )}
        </span>
      )}
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
  const [storyMode, setStoryMode] = useState(job.brief.story ? 'own' : 'ai');
  const [story, setStory] = useState(job.brief.story || '');
  const [writtenLine] = useState(job.storyboard?.scenes[0]?.voiceover || '');
  const [writtenText] = useState(job.storyboard?.scenes[0]?.on_screen_text || '');
  const [hookMode, setHookMode] = useState(
    job.storyboard?.hook_choice != null ? `h${job.storyboard.hook_choice}` : 'written',
  );
  const [ownHook, setOwnHook] = useState('');
  const [mode, setMode] = useState('video');
  const [lengthText, setLengthText] = useState(null); // the length box while typing
  const [lengthNote, setLengthNote] = useState('');
  const [undoBoard, setUndoBoard] = useState(null); // the scenes before "Apply" joined some
  const [keepMine, setKeepMine] = useState(false);
  const [sound, setSound] = useState({ voice: job.brief.voice, music: job.brief.music, captions: job.brief.captions });
  const n = board?.scenes.length ?? 3;
  const estimate = useMemo(() => estimateBoard(board, config?.prices, n, sound.voice), [board, config, n, sound.voice]);
  const hasStory = storyMode === 'own' || Boolean(job.brief.story);
  const newImages = board ? board.scenes.filter((s, i) => s.image_source === 'generate' && !isChained(board, i, s)).length : 0;
  const clips = useClipTexts(job, board); // what each clip gets, as you type (D30)
  const [shortened, setShortened] = useState({}); // scene -> its text before "Shorten it for me"

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
  // The whole video: the scenes plus the end card. Typed freely, applied on Enter or when leaving the box.
  const endCard = config?.end_card_s ?? 2;
  const scenesLength = board.scenes.slice(0, n).reduce((t, s) => t + s.duration_s, 0);
  const videoLength = scenesLength + endCard;
  const minVideo = MIN_SCENE_S * n + endCard;
  const maxVideo = MAX_SCENE_S * n + endCard;
  // Which number of scenes allows a video this short (each scene 2 s or more, plus the end card).
  const fewerScenesHint = (wanted) => {
    const fit = Math.floor((wanted - endCard) / MIN_SCENE_S);
    if (fit < 1) return ` The shortest possible video is ${MIN_SCENE_S + endCard} s (1 scene of ${MIN_SCENE_S} s).`;
    return ` For ${wanted} s, keep ${fit} ${fit === 1 ? 'scene' : 'scenes'}: remove the others with "Remove" in Scenes below.`;
  };
  const applyVideoLength = (text) => {
    const wanted = Math.round(Number(text) || videoLength);
    const total = Math.max(minVideo, Math.min(maxVideo, wanted));
    if (lengthText === null && wanted === videoLength) return; // nothing new typed: keep the page still
    setLengthText(null);
    setLengthNote(
      wanted < minVideo
        ? `${wanted} s is too short for ${n} ${n === 1 ? 'scene' : 'scenes'}. Each scene is at least 2 s, and the ${endCard} s end card comes on top, so with ${n} ${n === 1 ? 'scene' : 'scenes'} the shortest video is ${minVideo} s.${fewerScenesHint(wanted)}`
        : wanted > maxVideo
          ? `${wanted} s is too long for ${n} ${n === 1 ? 'scene' : 'scenes'}: each scene can be at most 10 s, so the longest is ${maxVideo} s. For a longer video, add a scene in Scenes below.`
          : '',
    );
    if (total === videoLength) return;
    const parts = splitLength(total - endCard, n);
    change({ ...board, scenes: board.scenes.map((s, i) => (i < n ? { ...s, duration_s: parts[i] } : s)) });
  };

  const hookField = sound.voice === 'none' ? 'on_screen_text' : 'voiceover';
  const writtenHook = hookField === 'voiceover' ? writtenLine : writtenText;
  function pickHook(mode, text) {
    setHookMode(mode);
    const line = mode === 'written' ? writtenHook : text;
    const choice = mode.startsWith('h') ? Number(mode.slice(1)) : null;
    change({
      ...board,
      hook_choice: choice,
      scenes: board.scenes.map((s, j) => (j === 0 ? { ...s, [hookField]: line } : s)),
    });
  }
  const editHookText = (i) => (e) => {
    const hooks = board.hooks.map((h, j) => (j === i ? { ...h, text: e.target.value } : h));
    const next = { ...board, hooks };
    if (hookMode === `h${i}`) next.scenes = board.scenes.map((s, j) => (j === 0 ? { ...s, [hookField]: e.target.value } : s));
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
      const make = newImages === 0 ? 'video' : mode;
      onChange(await api.approve(job.id, make));
      navigate(`/job/${job.id}${make === 'video' ? '/video' : ''}`);
    });

  const check = () => run('check', save);
  const changeSound = (patch) =>
    run('sound', async () => {
      setSound({ ...sound, ...patch });
      onChange(await api.setSound(job.id, patch));
    });
  const addScene = () =>
    change({
      ...board,
      scenes: (() => {
        const scenes = [...board.scenes];
        const blank = { ...scenes[Math.max(0, scenes.length - 2)], uid: '', description: '', voiceover: '', on_screen_text: '', image_prompt: '', motion_prompt: '', starts: '', ends: '', image_source: 'generate', image_upload_key: null, duration_s: 3 };
        scenes.splice(Math.max(scenes.length - 1, 1), 0, blank);
        const roles = rolesFor(scenes.length);
        return scenes.map((x, k) => ({ ...x, role: roles[k] }));
      })(),
    });
  // Recommendation: about 2.5 s per scene for this video's length; joining neighbours keeps people
  // and places more consistent (fewer separate clips) and costs less. Nothing is cut: texts are joined.
  const perScene = config?.seconds_per_scene ?? 2.5;
  const recommended = Math.max(1, Math.min(MAX_SCENES, Math.round(scenesLength / perScene)));
  // "0-2 s" / "0:00-0:02" / "0.00-0.02 s" in the second part move on by the first part's length.
  const shiftTimes = (text, by) =>
    text
      .replace(/(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)\s*s\b/g, (m, a, b) => `${+(Number(a) + by).toFixed(2)}-${+(Number(b) + by).toFixed(2)} s`)
      .replace(/(\d{1,2}):(\d{2})/g, (m, mm, ss) => {
        const t = Number(mm) * 60 + Number(ss) + by;
        return `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, '0')}`;
      });
  const joinScenes = (scenes, i) => {
    const a = scenes[i];
    const b = scenes[i + 1];
    const both = (x, y, sep = ' ') => [x, y].filter((t) => t && t.trim()).join(sep);
    const merged = {
      ...a,
      description: both(a.description, b.description),
      voiceover: both(a.voiceover, b.voiceover).slice(0, 400),
      on_screen_text: a.on_screen_text || b.on_screen_text,
      motion_prompt: both(a.motion_prompt, b.motion_prompt ? `Then, in the same take: ${shiftTimes(b.motion_prompt, a.duration_s)}` : ''),
      duration_s: Math.min(MAX_SCENE_S, a.duration_s + b.duration_s),
      ends: b.ends || a.ends || '', // the joined shot opens like the first part and ends like the second
    };
    const next = [...scenes.slice(0, i), merged, ...scenes.slice(i + 2)];
    const roles = rolesFor(next.length);
    return next.map((x, k) => ({ ...x, role: roles[k] }));
  };
  const applyRecommendation = () => {
    let scenes = board.scenes;
    while (scenes.length > recommended) {
      let best = 0;
      for (let k = 1; k < scenes.length - 1; k += 1) {
        if (scenes[k].duration_s + scenes[k + 1].duration_s < scenes[best].duration_s + scenes[best + 1].duration_s) best = k;
      }
      scenes = joinScenes(scenes, best);
    }
    setUndoBoard(board);
    change({ ...board, scenes });
  };
  const removeScene = (i) => {
    const scenes = board.scenes.filter((_, k) => k !== i);
    const roles = rolesFor(scenes.length);
    change({ ...board, scenes: scenes.map((x, k) => ({ ...x, role: roles[k] })) });
  };
  const uploads = (i) => job.assets.filter((a) => a.kind === 'upload' && a.scene_idx === i);
  const disabled = readOnly || Boolean(busy);
  const tooLong = clips.filter((c) => c.too_long_by > 0).length;
  const textOver = (board.notes || '').length > STORY_MAX;
  const shortenFor = async (i) => {
    setBusy(`shorten${i}`);
    setError('');
    try {
      const { text } = await api.shortenScene(job.id, i, board);
      setShortened({ ...shortened, [i]: board.scenes[i].motion_prompt });
      editScene(i, 'motion_prompt', text);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };
  const undoShorten = (i) => {
    editScene(i, 'motion_prompt', shortened[i]);
    const rest = { ...shortened };
    delete rest[i];
    setShortened(rest);
  };

  return (
    <div className="page">
      <Stepper step={2} job={job} />
      <BackButton onClick={() => goToBrief(job)}>Back to the brief</BackButton>
      <h1>{board.title}</h1>
      <p className="muted">
        {readOnly
          ? 'Approved: the storyboard is locked. On the Images step you can still edit the voiceover, text, motion and clip length before the video is made.'
          : 'Choose where the story comes from, check what you need, then continue. Nothing is made before you continue.'}
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
                <AutoTextarea
                  minRows={5}
                  value={story}
                  onChange={(e) => setStory(e.target.value)}
                  placeholder="For example: My grandad played every Sunday in boots that slipped. Now the whole team wears…"
                  disabled={disabled}
                  aria-label="Your story"
                />
                <CharCount value={story} max={STORY_MAX} label="Your story" />
                <div>
                  <button type="button" className="btn btn-secondary btn-small" onClick={buildFromStory} disabled={disabled || story.trim().length < 20 || story.length > STORY_MAX}>
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

      <SoundCard value={sound} theme={job.brief.theme} onChange={changeSound} disabled={disabled} />

      <section className="card">
        <h2>
          How the scenes connect <Help text={HELP.continuity} />
        </h2>
        <div className="choice-group" role="radiogroup" aria-label="How the scenes connect">
          <Choice name="continuity" value="continuous" checked={board.continuity === 'continuous'} onChange={() => change({ ...board, continuity: 'continuous' })} disabled={disabled} title="One connected video">
            <span className="muted small">
              Every scene flows into the next, with no jump. Only the first scene needs a picture; later scenes continue from the one before, or use your own picture.
            </span>
          </Choice>
          <Choice name="continuity" value="separate" checked={board.continuity === 'separate'} onChange={() => change({ ...board, continuity: 'separate' })} disabled={disabled} title="Separate shots">
            <span className="muted small">Each scene starts from its own picture, like cuts between different shots, with a soft blend at each cut.</span>
          </Choice>
        </div>
        {board.continuity === 'continuous' && (
          <p className="flow-note small">
            Every scene connects to the next one, also when you use your own pictures: the clip before a scene with your picture ends on that picture, so the cut matches.
          </p>
        )}
      </section>

      <details className="card fold" open={Boolean(board.notes)}>
        <summary>
          <span className="fold-title">
            Style and world notes (optional) <Help text={HELP.notes} />
          </span>
          <span className="muted small fold-sum">{board.notes ? 'Added to every scene' : 'None: the scenes speak for themselves'}</span>
        </summary>
        <p className="muted small">
          Anything that is true for the whole ad: look, place, weather, light, colours, camera rules. It is added to every scene&rsquo;s instructions, so all scenes match. Leave it empty if you are not sure.
        </p>
        <AutoTextarea
          minRows={3}
          value={board.notes || ''}
          onChange={(e) => change({ ...board, notes: e.target.value })}
          disabled={disabled}
          placeholder="For example: realistic phone video at night in the rain, neon reflections, cyan and magenta light, one continuous camera move."
          aria-label="Style and world notes"
        />
        {board.notes && <CharCount value={board.notes} max={STORY_MAX} label="The notes" />}
      </details>

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
          <div>
            <label htmlFor="adlen">
              Total video length (seconds) <Help text={HELP.ad_length} />
            </label>
            <input
              id="adlen"
              type="number"
              min={minVideo}
              max={maxVideo}
              value={lengthText ?? videoLength}
              onChange={(e) => setLengthText(e.target.value)}
              onBlur={(e) => applyVideoLength(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && applyVideoLength(e.currentTarget.value)}
              disabled={disabled}
            />
            <p className="muted small">
              Your video: {n} {n === 1 ? 'scene' : 'scenes'} (
              {board.scenes
                .slice(0, n)
                .map((s) => `${s.duration_s} s`)
                .join(' + ')}
              ) + {endCard} s end card = <strong>{videoLength} s</strong>.
              <br />
              With {n} {n === 1 ? 'scene' : 'scenes'} you can choose {minVideo} to {maxVideo} s (each scene 2–10 s).
            </p>
            {lengthNote && (
              <p className="notice small" role="status">
                <AlertTriangle size={14} aria-hidden="true" /> <span>{lengthNote}</span>
              </p>
            )}
          </div>
        </div>
      </section>

      {!readOnly && n > recommended && !keepMine && (
        <div className="notice recommend" role="status">
          <Sparkles size={16} aria-hidden="true" />
          <div>
            <strong>
              Recommended for this story and length: {recommended} {recommended === 1 ? 'scene' : 'scenes'} instead of {n}.
            </strong>{' '}
            Each scene is a separate AI clip, so fewer scenes keep the person and the place more consistent, and cost less.
            Applying joins neighbouring scenes into one continuous shot; nothing from your story is cut.
            <div className="row-actions">
              <button type="button" className="btn btn-secondary btn-small" onClick={applyRecommendation} disabled={disabled}>
                Apply: {recommended} {recommended === 1 ? 'scene' : 'scenes'}
              </button>
              <button type="button" className="btn btn-ghost btn-small" onClick={() => setKeepMine(true)}>
                Keep my {n} scenes
              </button>
            </div>
          </div>
        </div>
      )}
      {!readOnly && undoBoard && (
        <p className="muted small">
          Scenes joined into {n}.{' '}
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              change(undoBoard);
              setUndoBoard(null);
              setKeepMine(true);
            }}
          >
            Undo
          </button>
        </p>
      )}

      <details className="card fold" open={!hasStory}>
        <summary>
          <span className="fold-title">
            Scenes ({n}) <Help text={HELP.scenes} />
          </span>
          <span className="muted small fold-sum">
            {board.scenes
              .slice(0, n)
              .map((s, i) => `${i + 1}: ${s.duration_s} s, ${SOURCE_LABEL[s.image_source].toLowerCase()}`)
              .join(' · ')}
          </span>
        </summary>
      <div className="scenes scenes-list">
        {board.scenes.slice(0, n).map((s, i) => {
          const own = uploads(i).at(-1);
          return (
            <article key={i} className="card scene scene-wide">
              <div className="scene-head">
                <h2>
                  {sceneTitle(s, i)} <Help text={HELP[s.role]} />
                </h2>
                {!readOnly && n > 1 && (
                  <button type="button" className="btn btn-ghost btn-small" onClick={() => removeScene(i)} disabled={disabled} aria-label={`Remove scene ${i + 1}`}>
                    Remove
                  </button>
                )}
              </div>
              <ClipTooLong
                clip={clips[i]}
                busy={busy === `shorten${i}`}
                disabled={disabled}
                onShorten={() => shortenFor(i)}
                canUndo={shortened[i] != null}
                onUndo={() => undoShorten(i)}
              />
              <div className="scene-grid">
                <div className="scene-main">
                  <FieldLabel htmlFor={`d${i}`} text="What happens in this scene" help={HELP.description} />
                  <AutoTextarea id={`d${i}`} className={cls(`scenes.${i}.description`)} value={s.description} onChange={onScene(i, 'description')} disabled={disabled} />
                  <div className="grid-2 tight">
                    <div>
                      <FieldLabel htmlFor={`v${i}`} text="Voiceover" help={HELP.voiceover} />
                      <input id={`v${i}`} className={cls(`scenes.${i}.voiceover`)} value={s.voiceover} onChange={onScene(i, 'voiceover')} maxLength={400} disabled={disabled} placeholder={sound.voice === 'none' ? 'No voiceover in this ad' : 'Nothing is said in this scene'} />
                    </div>
                    <div>
                      <FieldLabel htmlFor={`t${i}`} text="On-screen text" help={HELP.on_screen_text} />
                      <input id={`t${i}`} className={cls(`scenes.${i}.on_screen_text`)} value={s.on_screen_text} onChange={onScene(i, 'on_screen_text')} maxLength={80} disabled={disabled} placeholder="No text on screen" />
                    </div>
                  </div>
                </div>
                <div className="scene-side">
                  <span className="label-like">
                    Starting picture <Help text={HELP.image_source} />
                  </span>
                  <div className="choice-row stack" role="radiogroup" aria-label={`Starting picture for scene ${i + 1}`}>
                    {['generate', 'product', 'upload'].map((src) => (
                      <Chip key={src} name={`src${i}`} value={src} checked={s.image_source === src} disabled={disabled || (src === 'upload' && !own)} onChange={() => editScene(i, 'image_source', src)}>
                        {src === 'generate' && isChained(board, i, { image_source: 'generate' }) ? `Continue from scene ${i}` : SOURCE_LABEL[src]}
                        {config && (
                          <span className="muted small">
                            {src === 'generate' && !isChained(board, i, { image_source: 'generate' }) ? formatMoney(config.prices.image, currency) : 'free'}
                          </span>
                        )}
                      </Chip>
                    ))}
                  </div>
                  {!readOnly && (
                    <label className="btn btn-ghost btn-small upload-btn">
                      {busy === `upload${i}` ? <Loader2 className="spin" size={14} aria-hidden="true" /> : <Upload size={14} aria-hidden="true" />} Upload a picture for this scene
                      <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={uploadFor(i)} disabled={disabled} />
                    </label>
                  )}
                  {s.image_source === 'upload' && own && <img className="scene-image" src={own.url} alt={`Your picture for scene ${i + 1}`} />}
                  {i > 0 && endsOnNext(board, i - 1) && <p className="flow-note small">Scene {i}&rsquo;s clip ends on this picture, so the cut matches.</p>}
                  <SceneLength
                    id={`len${i}`}
                    value={s.duration_s}
                    onChange={(v) => editScene(i, 'duration_s', v)}
                    disabled={disabled}
                    prices={config?.prices}
                    currency={currency}
                    endsOnNext={endsOnNext(board, i)}
                  />
                </div>
              </div>

              <details className="ai-instructions">
                <summary>
                  Show what the AI gets <span className="muted small">(the starting picture and the movement, written from this scene)</span>
                </summary>
                <div className="ai-pair">
                  <div className="ai-field">
                    <FieldLabel htmlFor={`ip${i}`} text="1. Starting picture (for the picture AI)" help={HELP.image_prompt} />
                    <p className="muted small hint">One frozen moment: the first frame, made from your product photo.</p>
                    {isChained(board, i, s) ? (
                      <p className="muted small">Not needed: this scene starts from the last frame of scene {i}.</p>
                    ) : s.image_source === 'generate' ? (
                      <AutoTextarea id={`ip${i}`} minRows={3} value={s.image_prompt} onChange={onScene(i, 'image_prompt')} disabled={disabled} />
                    ) : (
                      <p className="muted small">Not needed: this scene starts from your own picture.</p>
                    )}
                  </div>
                  <div className="ai-field">
                    <FieldLabel htmlFor={`mp${i}`} text="2. Movement (for the video AI)" help={HELP.motion_prompt} />
                    <p className="muted small hint">What changes, second by second: camera, people, light, the last frame.</p>
                    <AutoTextarea id={`mp${i}`} minRows={3} value={s.motion_prompt} onChange={onScene(i, 'motion_prompt')} disabled={disabled} />
                    {endsOnNext(board, i) && (
                      <p className="muted small hint">Ends on scene {i + 2}&rsquo;s picture, so the cut matches.</p>
                    )}
                  </div>
                </div>
                {board.continuity === 'continuous' && (
                  <div className="ai-flow">
                    <FieldLabel htmlFor={`fs${i}`} text="3. How it joins the scenes around it (added for you)" help={HELP.flow} />
                    <p className="muted small hint">Only the AI gets this; your story text stays as it is.</p>
                    <div className="ai-pair">
                      <div className="ai-field">
                        <label className="muted small" htmlFor={`fs${i}`}>{i === 0 ? 'How the ad opens' : `How it starts (matches the end of scene ${i})`}</label>
                        <AutoTextarea id={`fs${i}`} minRows={2} value={s.starts || ''} onChange={onScene(i, 'starts')} maxLength={800} disabled={disabled} placeholder="Nothing added" />
                      </div>
                      <div className="ai-field">
                        <label className="muted small" htmlFor={`fe${i}`}>{i === n - 1 ? 'How it ends (before the end card)' : `How it ends (matches the start of scene ${i + 2})`}</label>
                        <AutoTextarea id={`fe${i}`} minRows={2} value={s.ends || ''} onChange={onScene(i, 'ends')} maxLength={800} disabled={disabled} placeholder="Nothing added" />
                      </div>
                    </div>
                    {board.keep_same && !board.notes && <p className="muted small">Same in every scene: {board.keep_same}</p>}
                  </div>
                )}
                <ClipExact clip={clips[i]} n={board.continuity === 'continuous' ? 4 : 3} />
              </details>
            </article>
          );
        })}
      </div>
      {!readOnly && n < MAX_SCENES && (
        <button type="button" className="btn btn-secondary btn-small add-scene" onClick={addScene} disabled={disabled}>
          + Add a scene <Help text={HELP.add_scene} />
        </button>
      )}
      </details>

      <details className="card fold" open={!hasStory}>
        <summary>
          <span className="fold-title">
            First line of the ad {hasStory ? '(optional)' : ''} <Help text={HELP.hooks} />
          </span>
          <span className="muted small fold-sum">
            {hookMode === 'written'
              ? 'Kept as written'
              : hookMode === 'own'
                ? 'Your own line'
                : `${FORMULA_LABEL[board.hooks[Number(hookMode.slice(1))]?.formula]} idea`}
          </span>
        </summary>
        <p className="muted hook-intro">
          The first 1–2 seconds decide whether people keep watching. Choose the first line of your ad: it is{' '}
          {hookField === 'voiceover' ? (
            <strong>the first thing people hear</strong>
          ) : (
            <strong>the first text people see</strong>
          )}{' '}
          (scene 1&rsquo;s {hookField === 'voiceover' ? 'voiceover' : 'on-screen text, because this ad has no voiceover'}). Keep it as
          it is, or pick one of three ideas, each a different way to grab attention.
        </p>
        <div className="choice-group" role="radiogroup" aria-label="First line of the ad">
          <Choice name="hook" value="written" checked={hookMode === 'written'} onChange={() => pickHook('written')} disabled={disabled} title="Keep it as it is">
            <span className="muted small">
              {writtenHook ? `“${writtenHook}”` : hookField === 'voiceover' ? 'Scene 1 has no spoken line: the ad opens without words.' : 'Scene 1 has no text on screen.'}
            </span>
          </Choice>
          {board.hooks.map((h, i) => (
            <Choice
              key={h.formula}
              name="hook"
              value={`h${i}`}
              checked={hookMode === `h${i}`}
              onChange={() => pickHook(`h${i}`, h.text)}
              disabled={disabled}
              title={`Idea ${i + 1}: ${HOOK_KIND[h.formula]}`}
            >
              <span className="muted small">{HOOK_HOW[h.formula]}</span>
              <input type="text" className={cls(`hooks.${i}.text`)} value={h.text} onChange={editHookText(i)} maxLength={160} disabled={disabled} aria-label={`Idea ${i + 1}`} />
            </Choice>
          ))}
          <Choice name="hook" value="own" checked={hookMode === 'own'} onChange={() => pickHook('own', ownHook)} disabled={disabled} title="Write my own first line">
            <input
              type="text"
              value={ownHook}
              placeholder={hookField === 'voiceover' ? 'The first words people hear' : 'The first words people see'}
              maxLength={160}
              disabled={disabled}
              aria-label="Your own first line"
              onChange={(e) => {
                setOwnHook(e.target.value);
                if (hookMode === 'own') editScene(0, hookField, e.target.value);
              }}
            />
          </Choice>
        </div>
      </details>

      {!readOnly && (
        <div className="actions">
          {newImages > 0 ? (
            <div className="continue-row">
              <label htmlFor="make" className="label-like">
                Next <Help text={HELP.make} />
              </label>
              <select id="make" value={mode} onChange={(e) => setMode(e.target.value)} disabled={disabled}>
                <option value="video">Make the video now</option>
                <option value="images">Check the new pictures first</option>
              </select>
            </div>
          ) : (
            <p className="label-like">Next: make the video</p>
          )}
          <p className="muted small make-explain">
            {newImages === 0
              ? 'Every scene uses your own picture, so the video is made straight away.'
              : mode === 'video'
                ? `The ${newImages} missing ${newImages === 1 ? 'picture is' : 'pictures are'} made first, then the video, without stopping.`
                : `Only the ${newImages} missing ${newImages === 1 ? 'picture is' : 'pictures are'} made now. You look at them, can still edit, and then decide on the video.`}
          </p>
          {estimate && (
            <CostBox
              rows={[
                ...(newImages > 0
                  ? [[`${newImages} starting ${newImages === 1 ? 'picture' : 'pictures'}${mode === 'images' ? ' (now)' : ''}`, estimate.images]]
                  : []),
                [`Video: ${n} ${n === 1 ? 'clip' : 'clips'}${sound.voice !== 'none' ? ' and voiceover' : ''}${mode === 'images' && newImages > 0 ? ' (later, only if you choose it)' : ''}`, estimate.video],
              ]}
              total={mode === 'video' || newImages === 0 ? estimate.total : null}
              note={pictureNote(board.scenes.slice(0, n), board)}
              spend={job.spend}
              cap={job.cost_cap}
              currency={currency}
            />
          )}
          {config && (
            <p className="muted small models-line">
              AI used: pictures by <strong>{modelLabel(config.models.image)}</strong>, clips by{' '}
              <strong>{modelLabel(config.models.video)}</strong>
              {sound.voice !== 'none' && (
                <>
                  , voice by <strong>{modelLabel(config.models.tts)}</strong>
                </>
              )}
              . Choosing other models comes with the model comparison (M4).
            </p>
          )}
          {error && <p className="error" role="alert">{error}</p>}
          {tooLong > 0 && (
            <p className="error" role="alert">
              {tooLong === 1 ? 'One scene is' : `${tooLong} scenes are`} too long for the video AI: shorten {tooLong === 1 ? 'it' : 'them'} (or press &ldquo;Shorten it for me&rdquo;) to continue.
            </p>
          )}
          {textOver && <p className="error" role="alert">The style and world notes are too long: shorten them to continue.</p>}
          <button className="btn btn-primary" onClick={approve} disabled={disabled || tooLong > 0 || textOver}>
            {busy === 'approve' ? 'Starting…' : 'Continue →'}
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
  const [sound, setSound] = useState({ voice: job.brief.voice, music: job.brief.music, captions: job.brief.captions });
  const n = board.scenes.length;
  const estimate = useMemo(() => estimateBoard(board, config?.prices, n, sound.voice), [board, config, n, sound.voice]);
  const locked = readOnly || job.phase === 'video';
  const editScene = (i, field, value) =>
    setBoard({ ...board, scenes: board.scenes.map((s, j) => (j === i ? { ...s, [field]: value } : s)) });
  const clips = useClipTexts(job, board); // what each clip gets, as you type (D30)
  const [shortened, setShortened] = useState({});
  const [shortBusy, setShortBusy] = useState(null);
  const tooLong = clips.filter((c) => c.too_long_by > 0).length;
  async function shortenFor(i) {
    setShortBusy(i);
    setError('');
    try {
      const { text } = await api.shortenScene(job.id, i, board);
      setShortened({ ...shortened, [i]: board.scenes[i].motion_prompt });
      editScene(i, 'motion_prompt', text);
    } catch (err) {
      setError(err.message);
    } finally {
      setShortBusy(null);
    }
  }
  function undoShorten(i) {
    editScene(i, 'motion_prompt', shortened[i]);
    const rest = { ...shortened };
    delete rest[i];
    setShortened(rest);
  }

  async function changeSound(patch) {
    setSound({ ...sound, ...patch });
    try {
      onChange(await api.setSound(job.id, patch));
    } catch (err) {
      setError(err.message);
    }
  }

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
          : 'Check the pictures. You can still change each scene’s voiceover, text, motion and length. Then make the video, or keep the images only.'}
      </p>
      <div className="scenes">
        {board.scenes.slice(0, n).map((s, i) => {
          const image = job.assets.find((a) => a.kind === 'image' && a.scene_idx === i);
          const chained = isChained(board, i, s);
          return (
            <article key={i} className="card scene">
              <h2>
                {sceneTitle(s, i)} <Help text={HELP[s.role]} />
              </h2>
              {!locked && (
                <ClipTooLong
                  clip={clips[i]}
                  busy={shortBusy === i}
                  disabled={busy || shortBusy != null}
                  onShorten={() => shortenFor(i)}
                  canUndo={shortened[i] != null}
                  onUndo={() => undoShorten(i)}
                />
              )}
              {chained && !image ? (
                <p className="muted small chained-note">Starts where scene {i} ends (one continuous shot): its first frame is made with the video.</p>
              ) : image ? (
                <a href={image.url} target="_blank" rel="noreferrer">
                  <img className="scene-image" src={image.url} alt={`Scene ${i + 1}`} />
                </a>
              ) : (
                <p className="muted small">No image.</p>
              )}
              <p className="muted small">
                {chained ? `The last frame of scene ${i}` : s.image_source === 'generate' ? 'Generated' : s.image_source === 'product' ? 'Your product photo' : 'Your own image'}
              </p>
              {endsOnNext(board, i) && <p className="flow-note small">Its clip ends on scene {i + 2}&rsquo;s picture, so the cut matches.</p>}
              <FieldLabel htmlFor={`iv${i}`} text="Voiceover" help={HELP.voiceover} />
              <input id={`iv${i}`} value={s.voiceover} onChange={(e) => editScene(i, 'voiceover', e.target.value)} maxLength={400} disabled={locked} />
              <FieldLabel htmlFor={`it${i}`} text="On-screen text" help={HELP.on_screen_text} />
              <input id={`it${i}`} value={s.on_screen_text} onChange={(e) => editScene(i, 'on_screen_text', e.target.value)} maxLength={80} disabled={locked} />
              <SceneLength
                id={`ilen${i}`}
                value={s.duration_s}
                onChange={(v) => editScene(i, 'duration_s', v)}
                disabled={locked}
                prices={config?.prices}
                currency={currency}
                endsOnNext={endsOnNext(board, i)}
              />
              <FieldLabel htmlFor={`imp${i}`} text="Movement in the clip (sent to the AI)" help={HELP.motion_prompt} />
              <AutoTextarea id={`imp${i}`} minRows={4} value={s.motion_prompt} onChange={(e) => editScene(i, 'motion_prompt', e.target.value)} disabled={locked} />
              {clips[i] && (
                <p className={clips[i].too_long_by ? 'char-count over small' : 'char-count muted small'}>
                  The whole clip text: {clips[i].chars.toLocaleString('en-GB')} / {clips[i].limit.toLocaleString('en-GB')} characters
                </p>
              )}
            </article>
          );
        })}
      </div>
      {!locked && <SoundCard value={sound} theme={job.brief.theme} onChange={changeSound} />}
      {!locked && (
        <div className="actions">
          {estimate && <CostBox rows={[['Video and voice', estimate.video]]} spend={job.spend} cap={job.cost_cap} currency={currency} />}
          {error && <p className="error" role="alert">{error}</p>}
          <p className="muted small">
            Making the video adds the voiceover, one clip per scene, captions, music and the end card, in every format <Help text={HELP.make_video} />. You can close the tab while it runs.
          </p>
          {tooLong > 0 && (
            <p className="error" role="alert">
              {tooLong === 1 ? 'One scene is' : `${tooLong} scenes are`} too long for the video AI: shorten {tooLong === 1 ? 'it' : 'them'} (or press &ldquo;Shorten it for me&rdquo;) to continue.
            </p>
          )}
          <button className="btn btn-primary" onClick={makeVideo} disabled={busy || tooLong > 0}>
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
const RATIO_LABEL = { '9:16': '9:16 vertical', '1:1': '1:1 square', '4:5': '4:5 portrait', '16:9': '16:9 landscape' };
const STYLE_LABEL = { realistic: 'Realistic phone video', cinematic: 'Cinematic', '3d': '3D animation', '2d': '2D illustration / anime' };
const VOICE_LABEL = { marin: 'Marin', cedar: 'Cedar', coral: 'Coral', onyx: 'Onyx', none: 'No voiceover' };
const CAPTION_LABEL = { bold: 'Bold, a few words at a time', clean: 'Clean subtitles', off: 'Off' };

function StageIcon({ status }) {
  if (status === 'done') return <CheckCircle2 size={18} className="ok" aria-label="done" />;
  if (status === 'failed') return <XCircle size={18} className="bad" aria-label="failed" />;
  if (status === 'running' || status === 'submitted') return <Loader2 size={18} className="spin" aria-label="in progress" />;
  return <Circle size={18} className="muted" aria-label="waiting" />;
}

// The steps in the order they happen, each grouped over the scenes.
function progressGroups(job, n) {
  const videoPhase = job.phase === 'video';
  const scenes = job.storyboard?.scenes || [];
  const firstPictures = videoPhase ? n : scenes.slice(0, n).filter((s, i) => !isChained(job.storyboard, i, s)).length;
  const of = (stage) => job.stages.filter((s) => s.stage === stage);
  const status = (rows, expected) => {
    if (rows.some((r) => r.status === 'failed')) return 'failed';
    if (rows.length >= expected && rows.every((r) => r.status === 'done')) return 'done';
    if (rows.some((r) => ['running', 'submitted', 'done'].includes(r.status))) return 'running';
    return 'waiting';
  };
  const voiced = job.brief.voice !== 'none' ? (job.storyboard?.scenes || []).filter((s) => s.voiceover?.trim()).length : 0;
  const groups = [
    { label: 'Read the photo and write the storyboard', rows: [...of('analyze'), ...of('storyboard')], expected: 2 },
    { label: `Starting pictures (${firstPictures})`, rows: of('image'), expected: firstPictures },
  ];
  if (videoPhase) {
    if (voiced) groups.push({ label: `Voiceover (${voiced} ${voiced === 1 ? 'line' : 'lines'})`, rows: of('voice'), expected: voiced });
    groups.push({ label: `Video clips (${n})`, rows: of('video'), expected: n });
    groups.push({ label: 'Final edit: captions, music, end card, every shape', rows: of('compose'), expected: 1 });
  }
  return groups.map((g) => ({
    ...g,
    status: status(g.rows, g.expected),
    done: g.rows.filter((r) => r.status === 'done').length,
    error: g.rows.find((r) => r.error)?.error,
  }));
}

// "0:00 - 0:02 (Establish): text" -> { title: "Establish", text }
function sceneParts(description) {
  const m = description.match(/^(?:.*?)\d{1,2}:\d{2}\s*[-\u2013]\s*\d{1,2}:\d{2}\s*(?:\(([^)]*)\))?:?\s*(.*)$/s);
  const text = (m ? m[2] : description).trim();
  return { title: m && m[1] ? m[1] : '', text: text.length > 150 ? `${text.slice(0, 147)}…` : text };
}

function AdSummary({ job, variant, testMode }) {
  const currency = useCurrency();
  const [music, setMusic] = useState([]);
  useEffect(() => {
    api.music().then(setMusic, () => {});
  }, []);
  const b = job.brief;
  const scenes = job.storyboard?.scenes || [];
  const track = b.music === 'none' ? null : music.find((m) => m.id === (b.music === 'theme' ? b.theme || 'food' : b.music));
  const total = job.costs.reduce((acc, c) => add(acc, c.cost), ZERO);
  const tiles = [
    ['Length', variant?.duration_s ? `${variant.duration_s.toFixed(0)} s` : '—'],
    ['Scenes', String(scenes.length)],
    ['Style', STYLE_LABEL[b.visual_style] || b.visual_style],
    ['Voice', VOICE_LABEL[b.voice] || b.voice],
    ['Music', b.music === 'none' ? 'No music' : track ? `${track.title}` : '…', track ? `${track.artist} · CC0` : ''],
    ['Captions', CAPTION_LABEL[b.captions] || b.captions],
  ];
  return (
    <section className="card summary-card">
      <h2>About this ad</h2>
      <div className="tiles">
        {tiles.map(([label, value, sub]) => (
          <div className="tile" key={label}>
            <span className="tile-label">{label}</span>
            <span className="tile-value">{value}</span>
            {sub && <span className="tile-sub">{sub}</span>}
          </div>
        ))}
      </div>

      <h3>Story</h3>
      <ul className="story-list">
        {scenes.map((s, i) => {
          const { title, text } = sceneParts(s.description);
          return (
            <li key={i}>
              <span className="dot" aria-hidden="true" />
              <div className="story-text">
                {title && <strong>{title}</strong>}
                <span>{text}</span>
              </div>
              <span className="pill-time">{s.duration_s} s</span>
            </li>
          );
        })}
      </ul>

      <h3>Made with</h3>
      {job.costs.length ? (
        <table className="made-with">
          <tbody>
            {job.costs.map((c) => (
              <tr key={c.kind + c.model}>
                <td>{KIND_LABEL[c.kind] || c.kind}</td>
                <td className="muted">{modelLabel(c.model)}</td>
                <td className="num">{formatMoney(c.cost, currency)}</td>
              </tr>
            ))}
            <tr className="total">
              <td colSpan={2}>Total</td>
              <td className="num">{formatMoney(total, currency)}</td>
            </tr>
          </tbody>
        </table>
      ) : (
        <p className="muted small">No costs were recorded for this ad.</p>
      )}
      {testMode && (
        <p className="notice small">
          <AlertTriangle size={14} aria-hidden="true" />
          <span>
            Local test: no AI made these pictures or clips and nothing was paid. Each clip is your starting picture with a slow
            camera move; the prices show what a real run would cost.
          </span>
        </p>
      )}
    </section>
  );
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
      <div className="ratio-tabs" role="tablist" aria-label="Shape">
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
      <video
        key={current.url}
        src={`${current.url}#t=0.1`}
        controls
        playsInline
        preload="metadata"
        className="ad-player"
        style={{ aspectRatio: current.ratio.replace(':', ' / ') }}
      />
      <p className="small">
        <a href={current.url} download={current.name} target="_blank" rel="noreferrer">
          Open the {RATIO_LABEL[current.ratio] || current.ratio} video
        </a>{' '}
        <span className="muted">(right-click the video to save it)</span>
      </p>
      {Object.keys(variant.skipped || {}).length > 0 && (
        <p className="muted small">
          Not made in:{' '}
          {Object.entries(variant.skipped)
            .map(([r, why]) => `${r} (${why})`)
            .join('; ')}
          .
        </p>
      )}
      <p className="muted small">
        Every file is marked as AI-generated in its metadata. When you post, turn on the platform&rsquo;s AI-generated label.
      </p>
      {(stills.length > 0 || carousel.length > 0) && (
        <details className="extras fold-plain">
          <summary>Extra images for posting (optional)</summary>
          <p className="muted small">
            Made from your video, for platforms that also want pictures: a cover (thumbnail), one still per scene for picture
            ads, and a 4:5 carousel ending on your call to action. You do not need them to post the video.
          </p>
          <div className="thumbs">
            {[cover, ...stills, ...carousel].filter(Boolean).map((a) => (
              <a key={a.name} href={a.url} target="_blank" rel="noreferrer" title={a.name}>
                <img src={a.url} alt={a.name} />
              </a>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function GenerateStep({ job, onChange }) {
  const currency = useCurrency();
  const config = useConfig();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const n = Math.max(job.storyboard?.scenes.length ?? 1, ...job.stages.filter((s) => s.scene_idx >= 0).map((s) => s.scene_idx + 1));
  const idxs = Array.from({ length: n }, (_, i) => i);
  const videoPhase = job.phase === 'video';
  const groups = progressGroups(job, n);
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
        Back to the {videoPhase ? 'pictures' : 'storyboard'}
      </BackButton>
      <h1>
        {videoPhase && <Clapperboard size={26} aria-hidden="true" />} {finished ? 'Your video' : videoPhase ? 'Making your video' : 'Making the pictures'}
      </h1>
      <div className="video-layout">
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
                        <span className="muted small">{active ? 'Working…' : 'Not made yet'}</span>
                      </div>
                    )}
                    {n > 1 && <figcaption className="muted small">Scene {idx + 1}</figcaption>}
                  </figure>
                );
              })}
            </div>
          )}
        </section>

        <div className="side">
          {finished ? (
            <AdSummary job={job} variant={variant} testMode={config?.test_mode} />
          ) : (
            <section className="card">
              <h2>Progress</h2>
              <ul className="stages">
                {groups.map((g) => (
                  <li key={g.label}>
                    <StageIcon status={g.status} />
                    <span>
                      {g.label}
                      {g.expected > 1 && g.status === 'running' ? ` · ${g.done}/${g.expected}` : ''}
                    </span>
                    {g.error && <span className="error small">{g.error}</span>}
                  </li>
                ))}
              </ul>
              <p className="cost" aria-live="polite">
                Spent so far: <strong>{formatMoney(job.spend, currency)}</strong>{' '}
                <span className="muted">of a {formatMoney(job.cost_cap, currency)} cap</span>
              </p>
              {active && <p className="muted small">You can close this tab: it continues on the server. Come back to this page in this browser to see the result.</p>}
              {job.status === 'failed' && (
                <div className="failed">
                  <p className="error" role="alert">{job.last_error || 'Something failed.'}</p>
                  <p className="muted small">Trying again keeps the finished steps. Spend so far still counts toward the cap.</p>
                  <button className="btn btn-secondary" onClick={retry} disabled={busy}>
                    <RotateCcw size={16} aria-hidden="true" /> Try again
                  </button>
                  {error && <p className="error">{error}</p>}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ChevronDown, ImageUp, KeyRound, Loader2, Lock, Sparkles } from 'lucide-react';
import { api, getAccessCode, rememberJob, setAccessCode } from '../lib/api';
import { navigate, useCurrency } from '../lib/hooks';
import { formatMoney } from '../lib/money';

const PLATFORMS = {
  tiktok: 'TikTok',
  instagram_reels: 'Instagram Reels',
  youtube_shorts: 'YouTube Shorts',
  facebook: 'Facebook',
};
const RATIOS = { '9:16': '9:16 vertical', '1:1': '1:1 square', '4:5': '4:5 portrait', '16:9': '16:9 landscape' };

// Planned options (plan §7–§9). Shown so visitors can see what is coming; not sent to the API yet.
const GOALS = ['Sales', 'Awareness', 'Website visits'];
const THEMES = ['Sport', 'Beauty', 'Tech', 'Food', 'Fashion'];
const AD_TYPES = ['Testimonial', 'Product demo', 'Unboxing', 'Problem → solution'];
const PRESETS = ['Balanced', 'Budget', 'Best quality'];
const TONES = ['Energetic', 'Calm', 'Playful', 'Premium'];
const VOICES = ['Warm female', 'Calm male', 'Upbeat female', 'Deep male'];
const MUSIC = ['Upbeat', 'Chill', 'Cinematic', 'None'];
const CAPTIONS = ['Bold word-by-word', 'Clean subtitles', 'Off'];

function Soon() {
  return <span className="soon">Soon</span>;
}

function PreviewSelect({ id, label, options }) {
  return (
    <div>
      <label htmlFor={id}>
        {label} <Soon />
      </label>
      <select id={id} defaultValue={options[0]}>
        {options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}

function AccessBar({ onUnlocked }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { ok } = await api.checkAccess(code.trim());
      if (ok) {
        setAccessCode(code.trim());
        onUnlocked();
      } else setError('That code is not valid.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="access-bar" onSubmit={submit} aria-label="Access code">
      <p>
        <Lock size={15} aria-hidden="true" /> Early access: generating needs a code.
      </p>
      <div className="access-bar-input">
        <label htmlFor="code" className="sr-only">
          Access code
        </label>
        <input
          id="code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          autoComplete="off"
          placeholder="Access code"
          required
        />
        <button className="btn btn-secondary btn-small" disabled={busy || !code.trim()}>
          <KeyRound size={14} aria-hidden="true" /> {busy ? 'Checking…' : 'Unlock'}
        </button>
      </div>
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default function Brief() {
  const currency = useCurrency();
  const [config, setConfig] = useState(null);
  const [unlocked, setUnlocked] = useState(Boolean(getAccessCode()));
  const [photo, setPhoto] = useState(null);
  const [form, setForm] = useState({
    product_name: '',
    description: '',
    audience: '',
    offer: '',
    landing_url: '',
    platform: 'tiktok',
    aspect_ratio: '9:16',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.config().then(setConfig, (err) => setError(err.message));
  }, []);

  const preview = useMemo(() => (photo ? URL.createObjectURL(photo) : ''), [photo]);
  useEffect(() => () => preview && URL.revokeObjectURL(preview), [preview]);

  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });
  const locked = Boolean(config?.access_code_required && !unlocked);

  function pickPhoto(e) {
    const file = e.target.files?.[0];
    setError('');
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setError('Upload a JPEG, PNG or WebP photo.');
      return;
    }
    if (config && file.size > config.max_upload_mb * 1024 * 1024) {
      setError(`The photo is larger than ${config.max_upload_mb} MB.`);
      return;
    }
    setPhoto(file);
  }

  async function submit(e) {
    e.preventDefault();
    if (locked) return;
    if (!photo) {
      setError('Add a product photo first.');
      return;
    }
    setBusy(true);
    setError('');
    const brief = { ...form, landing_url: form.landing_url.trim() || null };
    try {
      const job = await api.createJob(brief, photo);
      rememberJob(job.id);
      navigate(`/job/${job.id}`);
    } catch (err) {
      if (err.status === 403) setUnlocked(false);
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Stepper step={1} />
      <header className="create-head">
        <h1>Start creating</h1>
        <p className="muted">
          One product photo and a short brief. You approve the storyboard before anything is rendered.
        </p>
      </header>

      <div className="card create-card">
        {locked && <AccessBar onUnlocked={() => setUnlocked(true)} />}

        <form onSubmit={submit}>
          <label className="dropzone" htmlFor="photo">
            {preview ? <img src={preview} alt="Your product" /> : <ImageUp size={34} aria-hidden="true" />}
            <strong>{photo ? photo.name : 'Drop in your product photo'}</strong>
            <span className="small">
              {photo ? 'Click to choose another' : `JPEG, PNG or WebP${config ? `, up to ${config.max_upload_mb} MB` : ''}`}
            </span>
          </label>
          <input id="photo" type="file" accept="image/jpeg,image/png,image/webp" onChange={pickPhoto} hidden />
          <p className="notice">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>
              Use a photo of the product only. If a person is in it, you need their consent, and the ad will show an
              AI-made version of them. Location data (EXIF/GPS) is removed when you upload.
            </span>
          </p>

          <div className="grid-2 tight">
            <div className="span-2">
              <label htmlFor="name">Product name</label>
              <input id="name" value={form.product_name} onChange={set('product_name')} maxLength={80} required />
            </div>
            <div className="span-2">
              <label htmlFor="desc">What is it, and why would someone want it?</label>
              <textarea
                id="desc"
                value={form.description}
                onChange={set('description')}
                minLength={10}
                maxLength={1000}
                rows={3}
                placeholder="E.g. Grip socks that stop your foot sliding in your boots, for amateur players."
                required
              />
            </div>
            <div>
              <label htmlFor="aud">Audience (optional)</label>
              <input id="aud" value={form.audience} onChange={set('audience')} maxLength={300} />
            </div>
            <div>
              <label htmlFor="offer">Offer or promo code (optional)</label>
              <input id="offer" value={form.offer} onChange={set('offer')} maxLength={200} />
            </div>
            <div className="span-2">
              <label htmlFor="url">Landing page URL (optional)</label>
              <input id="url" type="url" value={form.landing_url} onChange={set('landing_url')} placeholder="https://" />
            </div>
            <div>
              <label htmlFor="platform">Platform</label>
              <select id="platform" value={form.platform} onChange={set('platform')}>
                {Object.entries(PLATFORMS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="ratio">Aspect ratio</label>
              <select id="ratio" value={form.aspect_ratio} onChange={set('aspect_ratio')}>
                {Object.entries(RATIOS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <PreviewSelect id="goal" label="Goal" options={GOALS} />
            <PreviewSelect id="theme" label="Theme" options={THEMES} />
            <PreviewSelect id="adtype" label="Ad type" options={AD_TYPES} />
            <PreviewSelect id="preset" label="Model preset" options={PRESETS} />
          </div>

          <details className="advanced">
            <summary>
              <Sparkles size={16} aria-hidden="true" /> Advanced options <Soon />
              <ChevronDown size={16} aria-hidden="true" className="chev" />
            </summary>
            <p className="muted small">Hook Lab, brand kit, voice, music and captions. The brand kit is set once and reused.</p>
            <div className="grid-2 tight">
              <div className="span-2">
                <span className="label-like">Hook Lab</span>
                <label className="toggle" htmlFor="hooklab">
                  <input id="hooklab" type="checkbox" />
                  <span>Test three opening hooks and keep the best one (about 0.10 EUR more)</span>
                </label>
              </div>
              <div>
                <label htmlFor="logo">Logo</label>
                <input id="logo" type="file" accept="image/png,image/svg+xml" />
              </div>
              <div>
                <span className="label-like">Brand colours</span>
                <div className="swatches">
                  <input type="color" defaultValue="#6366f1" aria-label="Primary colour" />
                  <input type="color" defaultValue="#f0abfc" aria-label="Secondary colour" />
                  <input type="color" defaultValue="#0f172a" aria-label="Background colour" />
                </div>
              </div>
              <PreviewSelect id="tone" label="Tone of voice" options={TONES} />
              <PreviewSelect id="voice" label="Voiceover" options={VOICES} />
              <PreviewSelect id="music" label="Music" options={MUSIC} />
              <PreviewSelect id="captions" label="Captions" options={CAPTIONS} />
              <div className="span-2">
                <label htmlFor="email">Email me when it is ready</label>
                <input id="email" type="email" placeholder="you@example.com" autoComplete="off" />
              </div>
            </div>
          </details>

          <div className="actions">
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <p className="muted small">
              Options marked Soon are previews and are not used yet. Next, AI reads the photo and writes a storyboard
              (a few cents); nothing is rendered until you approve it.
              {config && <> Rendering then costs about {formatMoney(config.job_estimate, currency)}.</>}
            </p>
            <button className="btn btn-primary btn-wide" disabled={busy || locked}>
              {busy ? (
                <>
                  <Loader2 className="spin" size={18} aria-hidden="true" /> Reading the photo and writing the storyboard…
                </>
              ) : locked ? (
                <>
                  <Lock size={16} aria-hidden="true" /> Enter the access code to generate
                </>
              ) : (
                <>
                  <Sparkles size={16} aria-hidden="true" /> Write my storyboard
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function Stepper({ step }) {
  const steps = ['Brief', 'Storyboard', 'Generate'];
  return (
    <ol className="stepper" aria-label="Progress">
      {steps.map((s, i) => (
        <li key={s} className={i + 1 === step ? 'current' : i + 1 < step ? 'done' : ''} aria-current={i + 1 === step ? 'step' : undefined}>
          <span>{i + 1}</span> {s}
        </li>
      ))}
    </ol>
  );
}

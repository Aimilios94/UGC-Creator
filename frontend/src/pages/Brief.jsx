import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ImageUp, Loader2, Lock } from 'lucide-react';
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

function AccessGate({ onUnlocked }) {
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
    <form className="card narrow" onSubmit={submit}>
      <h2>
        <Lock size={18} aria-hidden="true" /> Access code
      </h2>
      <p className="muted">Generation is invite-only while the app is in early access.</p>
      <label htmlFor="code">Code</label>
      <input id="code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" required />
      {error && <p className="error" role="alert">{error}</p>}
      <button className="btn btn-primary" disabled={busy || !code.trim()}>
        {busy ? 'Checking…' : 'Continue'}
      </button>
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

  if (config?.access_code_required && !unlocked) {
    return (
      <div className="page">
        <Stepper step={1} />
        <AccessGate onUnlocked={() => setUnlocked(true)} />
      </div>
    );
  }

  return (
    <div className="page">
      <Stepper step={1} />
      <h1>Brief</h1>
      <form className="grid-2" onSubmit={submit}>
        <div className="card">
          <h2>Product photo</h2>
          <label className="dropzone" htmlFor="photo">
            {preview ? <img src={preview} alt="Your product" /> : <ImageUp size={36} aria-hidden="true" />}
            <span>{photo ? photo.name : 'Choose a JPEG, PNG or WebP photo'}</span>
          </label>
          <input id="photo" type="file" accept="image/jpeg,image/png,image/webp" onChange={pickPhoto} hidden />
          <p className="notice">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>
              Use a photo of the product only. If a person is in it, you need their consent, and the ad will show an
              AI-made version of them. Location data (EXIF/GPS) is removed when you upload.
            </span>
          </p>
        </div>

        <div className="card">
          <h2>About the product</h2>
          <label htmlFor="name">Product name</label>
          <input id="name" value={form.product_name} onChange={set('product_name')} maxLength={80} required />
          <label htmlFor="desc">What is it, and why would someone want it?</label>
          <textarea
            id="desc"
            value={form.description}
            onChange={set('description')}
            minLength={10}
            maxLength={1000}
            rows={4}
            required
          />
          <label htmlFor="aud">Audience (optional)</label>
          <input id="aud" value={form.audience} onChange={set('audience')} maxLength={300} />
          <label htmlFor="offer">Offer or promo code (optional, used exactly as written)</label>
          <input id="offer" value={form.offer} onChange={set('offer')} maxLength={200} />
          <label htmlFor="url">Landing page URL (optional)</label>
          <input id="url" type="url" value={form.landing_url} onChange={set('landing_url')} placeholder="https://" />
          <div className="grid-2 tight">
            <div>
              <label htmlFor="platform">Platform</label>
              <select id="platform" value={form.platform} onChange={set('platform')}>
                {Object.entries(PLATFORMS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="ratio">Aspect ratio</label>
              <select id="ratio" value={form.aspect_ratio} onChange={set('aspect_ratio')}>
                {Object.entries(RATIOS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="actions span-2">
          {error && <p className="error" role="alert">{error}</p>}
          <p className="muted small">
            Next, AI reads the photo and writes a storyboard (a few cents). Nothing is rendered until you approve it.
            {config && <> Rendering then costs about {formatMoney(config.job_estimate, currency)}.</>}
          </p>
          <button className="btn btn-primary" disabled={busy}>
            {busy ? (
              <>
                <Loader2 className="spin" size={18} aria-hidden="true" /> Reading the photo and writing the storyboard…
              </>
            ) : (
              'Write my storyboard'
            )}
          </button>
        </div>
      </form>
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

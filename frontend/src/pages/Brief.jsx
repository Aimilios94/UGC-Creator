import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ChevronDown, ImageUp, KeyRound, Loader2, Lock, Sparkles } from 'lucide-react';
import { api, getAccessCode, rememberJob, setAccessCode } from '../lib/api';
import { navigate, useCurrency } from '../lib/hooks';
import { formatMoney } from '../lib/money';
import { Help } from '../components/Help';
import { HELP } from '../lib/help';
import Stepper from '../components/Stepper';

const PLATFORMS = {
  tiktok: 'TikTok',
  instagram_reels: 'Instagram Reels',
  youtube_shorts: 'YouTube Shorts',
  facebook: 'Facebook',
};
const RATIOS = { '9:16': '9:16 vertical', '1:1': '1:1 square', '4:5': '4:5 portrait', '16:9': '16:9 landscape' };

// Brief options sent to the API (values match backend/app/models.py).
const GOALS = { sales: 'Sales', awareness: 'Awareness', traffic: 'Website visits' };
const THEMES = { '': 'No theme', sport: 'Sport', beauty: 'Beauty', tech: 'Tech', food: 'Food', fashion: 'Fashion' };
const AD_TYPES = {
  product_demo: 'Product demo',
  problem_solution: 'Problem → solution',
  unboxing: 'Unboxing',
  testimonial: 'Testimonial (your quotes only)',
};
const TONES = { '': 'Theme default', energetic: 'Energetic', calm: 'Calm', playful: 'Playful', premium: 'Premium' };
const FONTS = ['Inter', 'Montserrat', 'Bebas Neue', 'Playfair Display'];
const VOICES = { marin: 'Marin (recommended)', cedar: 'Cedar', coral: 'Coral', onyx: 'Onyx' };
const MUSIC = { theme: "The theme's track", none: 'No music' };
const CAPTIONS = { bold: 'Bold, a few words at a time', clean: 'Clean subtitles', off: 'Off' };
const STYLES = {
  realistic: 'Realistic phone video (UGC)',
  cinematic: 'Cinematic',
  '3d': '3D animation',
  '2d': '2D illustration / anime',
};
const DEFAULT_COLORS = { primary: '#6366f1', secondary: '#f0abfc', background: '#0f172a' };

// Planned options (plan §7–§10). Shown so visitors can see what is coming; not sent to the API yet.
const PRESETS = ['Balanced', 'Budget', 'Best quality'];

function Soon() {
  return <span className="soon">Soon</span>;
}

function Select({ id, label, value, onChange, options, help }) {
  return (
    <div>
      <label htmlFor={id}>
        {label}
        {help && <Help text={help} />}
      </label>
      <select id={id} value={value} onChange={onChange}>
        {Object.entries(options).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </div>
  );
}

function BrandKitFields({ kit, setKit, locked, onSaved }) {
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const colors = { ...DEFAULT_COLORS, ...(kit.colors || {}) };
  const setColor = (name) => (e) => setKit({ ...kit, colors: { ...colors, [name]: e.target.value } });

  async function save() {
    setBusy('save');
    setError('');
    setMsg('');
    try {
      const saved = await api.saveBrandKit({ tone: kit.tone || null, font: kit.font || null, colors });
      onSaved(saved);
      setMsg('Brand kit saved. It is reused for every ad from this browser.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  async function uploadLogo(e) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setBusy('logo');
    setError('');
    setMsg('');
    try {
      onSaved(await api.uploadLogo(file));
      setMsg('Logo saved.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  return (
    <>
      <div>
        <label htmlFor="logo">Logo (PNG with transparency works best)</label>
        <div className="logo-row">
          {kit.logo_url && <img src={kit.logo_url} alt="Your logo" className="logo-preview" />}
          <input id="logo" type="file" accept="image/png,image/jpeg,image/webp" onChange={uploadLogo} disabled={locked || !!busy} />
        </div>
      </div>
      <div>
        <span className="label-like">Brand colours</span>
        <div className="swatches">
          <input type="color" value={colors.primary} onChange={setColor('primary')} aria-label="Primary colour" />
          <input type="color" value={colors.secondary} onChange={setColor('secondary')} aria-label="Secondary colour" />
          <input type="color" value={colors.background} onChange={setColor('background')} aria-label="Background colour" />
        </div>
      </div>
      <Select
        id="tone"
        label="Tone of voice"
        value={kit.tone || ''}
        onChange={(e) => setKit({ ...kit, tone: e.target.value })}
        options={TONES}
      />
      <Select
        id="font"
        label="Caption font"
        value={kit.font || 'Inter'}
        onChange={(e) => setKit({ ...kit, font: e.target.value })}
        options={Object.fromEntries(FONTS.map((f) => [f, f]))}
      />
      <div className="span-2 row">
        <button type="button" className="btn btn-secondary btn-small" onClick={save} disabled={locked || !!busy}>
          {busy === 'save' ? 'Saving…' : 'Save brand kit'}
        </button>
        {locked && <span className="muted small">Enter the access code to save a brand kit.</span>}
        {msg && <span className="ok small">{msg}</span>}
        {error && (
          <span className="error small" role="alert">
            {error}
          </span>
        )}
      </div>
    </>
  );
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

// "Back to the brief" from a storyboard fills the form with that brief (the photo is picked again).
function readPrefill() {
  try {
    const raw = sessionStorage.getItem('ugc.prefill');
    if (!raw) return {};
    sessionStorage.removeItem('ugc.prefill');
    const b = JSON.parse(raw);
    return { ...b, landing_url: b.landing_url || '', theme: b.theme || '', goal: b.goal || 'sales', story: b.story || '' };
  } catch {
    return {};
  }
}

export default function Brief() {
  const currency = useCurrency();
  const [config, setConfig] = useState(null);
  const [unlocked, setUnlocked] = useState(Boolean(getAccessCode()));
  const [photo, setPhoto] = useState(null);
  const [form, setForm] = useState(() => ({
    product_name: '',
    description: '',
    audience: '',
    offer: '',
    landing_url: '',
    platform: 'tiktok',
    aspect_ratio: '9:16',
    goal: 'sales',
    theme: '',
    ad_type: 'product_demo',
    voice: 'marin',
    music: 'theme',
    captions: 'bold',
    visual_style: 'realistic',
    story: '',
    ...readPrefill(),
  }));
  const [campaigns, setCampaigns] = useState([]);
  const [campaignId, setCampaignId] = useState('');
  const [campaignName, setCampaignName] = useState('');
  const [kit, setKit] = useState({});
  const [hasKit, setHasKit] = useState(false);
  const [useKit, setUseKit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.config().then(setConfig, (err) => setError(err.message));
    api.campaigns().then(setCampaigns, () => {});
    api.getBrandKit().then(
      (k) => {
        if (k) {
          setKit(k);
          setHasKit(true);
          setUseKit(true);
        }
      },
      () => {},
    );
  }, []);

  function pickCampaign(e) {
    const id = e.target.value;
    setCampaignId(id);
    const c = campaigns.find((x) => x.id === id);
    if (c) {
      setForm((f) => ({
        ...f,
        goal: c.goal || f.goal,
        audience: c.audience,
        offer: c.offer,
        landing_url: c.landing_url || '',
      }));
    }
  }

  function brandSaved(saved) {
    setKit(saved);
    setHasKit(true);
    setUseKit(true);
  }

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
    const brief = { ...form, landing_url: form.landing_url.trim() || null, theme: form.theme || null, story: form.story.trim() };
    try {
      const job = await api.createJob(brief, photo, {
        campaignId,
        campaignName: campaignId ? '' : campaignName.trim(),
        useBrandKit: hasKit && useKit,
      });
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
            <div>
              <label htmlFor="campaign">Campaign</label>
              <select id="campaign" value={campaignId} onChange={pickCampaign}>
                <option value="">New campaign</option>
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.ads} {c.ads === 1 ? 'ad' : 'ads'})
                  </option>
                ))}
              </select>
            </div>
            <div>
              {campaignId ? (
                <p className="muted small campaign-hint">This ad joins the campaign. Its brief is filled in below; edit it if this ad differs.</p>
              ) : (
                <>
                  <label htmlFor="cname">Campaign name (optional)</label>
                  <input
                    id="cname"
                    value={campaignName}
                    onChange={(e) => setCampaignName(e.target.value)}
                    maxLength={80}
                    placeholder="Defaults to the product name"
                  />
                </>
              )}
            </div>
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
            <Select id="goal" label="Goal" value={form.goal} onChange={set('goal')} options={GOALS} help={HELP.goal} />
            <Select id="theme" label="Theme" value={form.theme} onChange={set('theme')} options={THEMES} help={HELP.theme} />
            <Select id="adtype" label="Ad type" value={form.ad_type} onChange={set('ad_type')} options={AD_TYPES} help={HELP.ad_type} />
            <Select id="style" label="Visual style" value={form.visual_style} onChange={set('visual_style')} options={STYLES} help={HELP.visual_style} />
            <div className="span-2">
              <label htmlFor="story">
                Your own story or script (optional)
                <Help text={HELP.story} />
              </label>
              <textarea
                id="story"
                rows={4}
                value={form.story}
                onChange={set('story')}
                maxLength={4000}
                placeholder="Leave empty and the AI writes the story from your brief. Or paste yours: your spoken lines are kept word for word."
              />
            </div>
            <PreviewSelect id="preset" label="Model preset" options={PRESETS} />
          </div>

          <details className="advanced">
            <summary>
              <Sparkles size={16} aria-hidden="true" /> Advanced options
              <ChevronDown size={16} aria-hidden="true" className="chev" />
            </summary>
            <p className="muted small">
              Brand kit (set once, reused for every ad from this browser), Hook Lab, voice, music and captions.
            </p>
            <div className="grid-2 tight">
              <div className="span-2">
                <span className="label-like">Brand kit</span>
                <label className="toggle" htmlFor="usekit">
                  <input
                    id="usekit"
                    type="checkbox"
                    checked={hasKit && useKit}
                    disabled={!hasKit}
                    onChange={(e) => setUseKit(e.target.checked)}
                  />
                  <span>
                    {hasKit
                      ? 'Use my brand kit in this ad (its tone is used in the script; logo, colours and font in the edit)'
                      : 'Save a brand kit below to use it in your ads'}
                  </span>
                </label>
              </div>
              <BrandKitFields kit={kit} setKit={setKit} locked={locked} onSaved={brandSaved} />
              <div className="span-2">
                <span className="label-like">
                  Hook Lab <Soon />
                </span>
                <label className="toggle" htmlFor="hooklab">
                  <input id="hooklab" type="checkbox" />
                  <span>Test three opening hooks and keep the best one (about 0.10 EUR more)</span>
                </label>
              </div>
              <Select id="voice" label="Voiceover (AI voice)" value={form.voice} onChange={set('voice')} options={VOICES} help={HELP.voice} />
              <Select id="music" label="Music" value={form.music} onChange={set('music')} options={MUSIC} help={HELP.music} />
              <Select id="captions" label="Captions" value={form.captions} onChange={set('captions')} options={CAPTIONS} help={HELP.captions} />
              <div className="span-2">
                <label htmlFor="email">
                  Email me when it is ready <Soon />
                </label>
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

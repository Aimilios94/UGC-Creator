import { useEffect, useRef, useState } from 'react';
import { ListMusic, Pause, Play } from 'lucide-react';
import { api, apiUrl } from '../lib/api';
import { HELP } from '../lib/help';
import { Help } from './Help';

const CAPTIONS = { bold: 'Bold, a few words at a time', clean: 'Clean subtitles', off: 'Off' };

// One audio element for every preview, so only one plays at a time.
function usePreview() {
  const audio = useRef(null);
  const [playing, setPlaying] = useState('');
  useEffect(() => () => audio.current?.pause(), []);
  function toggle(id, src) {
    if (!audio.current) {
      audio.current = new Audio();
      audio.current.onended = () => setPlaying('');
    }
    if (playing === id) {
      audio.current.pause();
      setPlaying('');
      return;
    }
    audio.current.src = src;
    audio.current.play().then(
      () => setPlaying(id),
      () => setPlaying(''),
    );
  }
  return { playing, toggle };
}

function PlayButton({ id, src, preview, label }) {
  if (!src) return null;
  const on = preview.playing === id;
  return (
    <button type="button" className="icon-btn" onClick={() => preview.toggle(id, src)} aria-label={`${on ? 'Stop' : 'Play'} ${label}`}>
      {on ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
    </button>
  );
}

function PickList({ title, items, value, onPick, preview, disabled }) {
  return (
    <div className="pick-list" role="listbox" aria-label={title}>
      {items.map((it) => (
        <div key={it.id} className={`pick-item${value === it.id ? ' selected' : ''}`} role="option" aria-selected={value === it.id}>
          <PlayButton id={it.id} src={it.sample} preview={preview} label={it.label} />
          <button type="button" className="pick-label" onClick={() => onPick(it.id)} disabled={disabled}>
            <span>{it.label}</span>
            {it.note && <span className="muted small">{it.note}</span>}
          </button>
        </div>
      ))}
    </div>
  );
}

// Voice, music and captions for the ad, with previews. `value` is the brief; `onChange` saves.
export default function SoundCard({ value, theme, onChange, disabled }) {
  const [voices, setVoices] = useState([]);
  const [music, setMusic] = useState([]);
  const [open, setOpen] = useState('');
  const preview = usePreview();

  useEffect(() => {
    api.voices().then(setVoices, () => {});
    api.music().then(setMusic, () => {});
  }, []);

  const voiceItems = [
    ...voices.map((v) => ({ id: v.id, label: v.label, sample: v.sample ? apiUrl(v.sample) : null })),
    { id: 'none', label: 'No voiceover', note: 'Music and on-screen text only' },
  ];
  const themeTrack = music.find((m) => m.id === theme);
  const musicItems = [
    {
      id: 'theme',
      label: "The theme's track",
      note: themeTrack ? `${themeTrack.title} (${themeTrack.artist})` : 'Food track when there is no theme',
      sample: themeTrack ? apiUrl(themeTrack.sample) : music.find((m) => m.id === 'food') && apiUrl(music.find((m) => m.id === 'food').sample),
    },
    ...music.map((m) => ({ id: m.id, label: `${m.title}`, note: `${m.artist} · ${m.id}`, sample: apiUrl(m.sample) })),
    { id: 'none', label: 'No music' },
  ];
  const labelOf = (items, id) => items.find((i) => i.id === id)?.label || id;

  return (
    <section className="card sound">
      <h2>
        Sound <Help text={HELP.sound} />
      </h2>
      <div className="grid-3 tight">
        <div>
          <span className="label-like">
            Voiceover <Help text={HELP.voice} />
          </span>
          <button type="button" className="picker" onClick={() => setOpen(open === 'voice' ? '' : 'voice')} aria-expanded={open === 'voice'} disabled={disabled}>
            <span>{labelOf(voiceItems, value.voice)}</span>
            <ListMusic size={16} aria-hidden="true" />
          </button>
        </div>
        <div>
          <span className="label-like">
            Music <Help text={HELP.music} />
          </span>
          <button type="button" className="picker" onClick={() => setOpen(open === 'music' ? '' : 'music')} aria-expanded={open === 'music'} disabled={disabled}>
            <span>{labelOf(musicItems, value.music)}</span>
            <ListMusic size={16} aria-hidden="true" />
          </button>
        </div>
        <div>
          <label htmlFor="captions-pick">
            Captions <Help text={HELP.captions} />
          </label>
          <select id="captions-pick" value={value.captions} onChange={(e) => onChange({ captions: e.target.value })} disabled={disabled}>
            {Object.entries(CAPTIONS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
      </div>
      {open === 'voice' && (
        <PickList title="Voices" items={voiceItems} value={value.voice} preview={preview} disabled={disabled} onPick={(id) => { onChange({ voice: id }); setOpen(''); }} />
      )}
      {open === 'music' && (
        <PickList title="Music" items={musicItems} value={value.music} preview={preview} disabled={disabled} onPick={(id) => { onChange({ music: id }); setOpen(''); }} />
      )}
      {open && <p className="muted small">Press ▶ to listen, then pick one. The music is licensed for ads (CC0); the voices are AI voices.</p>}
    </section>
  );
}

import { Loader2, Scissors, Undo2 } from 'lucide-react';
import { CLIP_MAX } from './CharCount';

const fmt = (n) => n.toLocaleString('en-GB');
const MOVE_MAX = 1400; // the movement part of a clip built from the structure (strategy plan, phase 4)
const FIELD = { description: 'What happens in this scene', motion_prompt: '2. Movement' };
const PART = {
  movement: 'Movement',
  who: 'Who and the product',
  start_end: 'How it starts and ends',
  place: 'Place and look',
  notes: 'Your style and world notes',
  rules: 'Fixed rules',
};
const NOTES = {
  full: 'your style and world notes in full',
  short: 'your style and world notes, shortened for this scene (they are too long for every clip)',
  none: 'no style and world notes',
};

// Shown on a scene whose own movement text cannot fit the video AI's 2,500 characters (D30).
export function ClipTooLong({ clip, busy, onShorten, canUndo, onUndo, disabled, undoField }) {
  if (!clip?.too_long_by && !canUndo) return null;
  return (
    <div className={clip?.too_long_by ? 'clip-over' : 'clip-over ok'} role={clip?.too_long_by ? 'alert' : undefined}>
      {clip?.too_long_by ? (
        clip.parts?.length ? (
          <p>
            This scene&rsquo;s own text is <strong>{fmt(clip.too_long_by)} characters too long</strong> for its clip: the movement can take up to {fmt(MOVE_MAX)}, so there is room for who is in it, the place and the fixed rules. Shorten it yourself in &ldquo;{FIELD[clip.shorten_field] || FIELD.motion_prompt}&rdquo;, or let the AI do it (a fraction of a cent; you see the result first).
          </p>
        ) : (
          <p>
            The video AI reads at most {fmt(CLIP_MAX)} characters per clip, and this scene&rsquo;s movement text is{' '}
            <strong>{fmt(clip.too_long_by)} characters too long</strong>. Shorten it yourself in &ldquo;2. Movement&rdquo;, or let the AI do it (a fraction of a cent; you see the result first).
          </p>
        )
      ) : (
        <p>Shortened by the AI. Check it in &ldquo;{FIELD[undoField] || FIELD.motion_prompt}&rdquo;, or undo.</p>
      )}
      <div className="clip-over-actions">
        {clip?.too_long_by > 0 && (
          <button type="button" className="btn btn-secondary btn-small" onClick={onShorten} disabled={disabled || busy}>
            {busy ? <Loader2 className="spin" size={14} aria-hidden="true" /> : <Scissors size={14} aria-hidden="true" />} Shorten it for me
          </button>
        )}
        {canUndo && (
          <button type="button" className="btn btn-ghost btn-small" onClick={onUndo} disabled={disabled || busy}>
            <Undo2 size={14} aria-hidden="true" /> Undo
          </button>
        )}
      </div>
    </div>
  );
}

// "Show what the AI gets", last part: the exact clip text and its length.
export function ClipExact({ clip, n }) {
  if (!clip) return null;
  const full = clip.chars >= clip.limit - 20;
  return (
    <div className="ai-exact">
      <p className="label-like">
        {n}. Exactly what the video AI gets{' '}
        <span className={clip.too_long_by ? 'char-count over small' : full ? 'muted small' : 'muted small'}>
          ({fmt(clip.chars)} / {fmt(clip.limit)} characters)
        </span>
      </p>
      {clip.parts?.length ? (
        <>
          <p className="muted small hint">Built from your scene and the cast and world, most important first, each part within its budget: your words word for word, then the AI&rsquo;s guesses where you said nothing, then the fixed rules.</p>
          <ul className="clip-parts small">
            {clip.parts.map((p) => (
              <li key={p.name} className={p.chars > p.budget ? 'over' : undefined}>
                {PART[p.name] || p.name} <span className="muted">{fmt(p.chars)} / {fmt(p.budget)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted small hint">Your scene&rsquo;s movement word for word, the joining notes, {NOTES[clip.notes] || NOTES.none}, then the app&rsquo;s fixed rules.</p>
      )}
      <div className="ai-exact-text">{clip.text}</div>
      {clip.negative && (
        <p className="muted small hint">
          Kept out of the picture (sent in the video AI&rsquo;s separate &ldquo;avoid&rdquo; field): {clip.negative}
        </p>
      )}
    </div>
  );
}

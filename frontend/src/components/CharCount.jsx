// Live character count under a long text box. Text is never cut silently (D30): over the limit,
// a clear message says by how much, and the page blocks the next step until it is shortened.
export const STORY_MAX = 12000; // the user's story and its style notes
export const CLIP_MAX = 2500; // what the video AI reads per clip (Kling on fal)

const fmt = (n) => n.toLocaleString('en-GB');

export default function CharCount({ value, max, label = 'This text' }) {
  const n = (value || '').length;
  const over = n - max;
  return (
    <p className={over > 0 ? 'char-count over small' : 'char-count muted small'} role={over > 0 ? 'alert' : undefined}>
      {fmt(n)} / {fmt(max)} characters
      {over > 0 && <> · {label} is {fmt(over)} characters too long. Nothing was cut: shorten it to continue.</>}
    </p>
  );
}

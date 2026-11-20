// Plain names for the AI models (the API reports model ids).
const LABELS = [
  ['fal-ai/nano-banana', 'Nano Banana (Google), on fal'],
  ['fal-ai/kling-video/v2.5-turbo/pro', 'Kling 2.5 Turbo Pro, on fal'],
  ['gpt-4o-mini-tts', 'gpt-4o-mini-tts (OpenAI)'],
  ['gpt-5-mini', 'GPT-5 mini (OpenAI)'],
  ['own-product', 'your product photo'],
  ['own-upload', 'your own picture'],
  ['mock', 'test stand-in (no AI)'],
];

export function modelLabel(id) {
  const hit = LABELS.find(([prefix]) => (id || '').startsWith(prefix));
  return hit ? hit[1] : id;
}

export const KIND_LABEL = {
  llm: 'Story and script',
  image: 'Starting pictures',
  tts: 'Voiceover',
  video: 'Video clips',
};

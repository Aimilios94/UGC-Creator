import { useEffect, useState } from 'react';
import { api } from './api';

// The exact text each clip would get, for the storyboard on screen (refreshed as you type).
export function useClipTexts(job, board) {
  const [clips, setClips] = useState(job.clips || []);
  useEffect(() => {
    if (!board) return undefined;
    const t = setTimeout(() => {
      api.clipTexts(job.id, board).then(setClips, () => {});
    }, 400);
    return () => clearTimeout(t);
  }, [job.id, board]);
  return clips;
}

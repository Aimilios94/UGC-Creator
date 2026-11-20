import { navigate } from './hooks';

// The four steps. Each step already reached is clickable, so you can go back and look.
export function goToBrief(job) {
  try {
    if (job) sessionStorage.setItem('ugc.prefill', JSON.stringify(job.brief));
  } catch {
    /* not essential */
  }
  navigate('/create');
}

export function stepLinks(job) {
  if (!job) return { brief: true };
  const imagesReached = job.status !== 'draft';
  return {
    brief: true,
    storyboard: Boolean(job.storyboard),
    images: imagesReached,
    video: job.phase === 'video' && job.status !== 'draft',
  };
}

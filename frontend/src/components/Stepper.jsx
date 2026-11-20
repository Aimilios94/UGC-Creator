import { navigate } from '../lib/hooks';
import { goToBrief, stepLinks } from '../lib/steps';

export default function Stepper({ step, job }) {
  const links = stepLinks(job);
  const go = {
    brief: () => goToBrief(job),
    storyboard: () => navigate(`/job/${job.id}/storyboard`),
    images: () => navigate(`/job/${job.id}/images`),
    video: () => navigate(`/job/${job.id}/video`),
  };
  const steps = [
    ['brief', 'Brief'],
    ['storyboard', 'Storyboard'],
    ['images', 'Images'],
    ['video', 'Video'],
  ];
  return (
    <ol className="stepper" aria-label="Progress">
      {steps.map(([key, label], i) => {
        const n = i + 1;
        const cls = n === step ? 'current' : n < step ? 'done' : '';
        const content = (
          <>
            <span>{n}</span> {label}
          </>
        );
        return (
          <li key={key} className={cls} aria-current={n === step ? 'step' : undefined}>
            {links[key] && n !== step ? (
              <button type="button" className="step-link" onClick={go[key]}>
                {content}
              </button>
            ) : (
              content
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function BackButton({ onClick, children = 'Back' }) {
  return (
    <button type="button" className="btn btn-ghost btn-small back" onClick={onClick}>
      ← {children}
    </button>
  );
}

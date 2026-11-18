import { ArrowRight, Camera, CheckCircle2, Film, PenLine } from 'lucide-react';
import { recentJobs } from '../lib/api';

const STEPS = [
  { icon: Camera, title: 'Brief', text: 'Upload one product photo and say what it is and who it is for.' },
  { icon: PenLine, title: 'Storyboard', text: 'AI writes a 3-scene plan with three hook ideas. You edit and approve it.' },
  { icon: Film, title: 'Generate', text: 'Only after you approve: a reference image of your real product, then a video clip.' },
  { icon: CheckCircle2, title: 'Review', text: 'Watch the result, with the cost of every step shown in euros.' },
];

const EXAMPLES = [
  { src: '/assets/skincare.png', alt: 'Illustration: a person applying a skincare serum at home' },
  { src: '/assets/tech.png', alt: 'Illustration: hands unboxing a laptop on a wooden table' },
  { src: '/assets/fashion.png', alt: 'Illustration: a mirror selfie video of a summer outfit' },
];

export default function Landing() {
  const recent = recentJobs();
  return (
    <>
      <section className="hero">
        <p className="eyebrow">Product photo in, UGC-style video ad out</p>
        <h1>
          Turn one product photo into a <span className="text-gradient">ready-to-post video ad</span>
        </h1>
        <p className="lead">
          A studio that keeps your real product in every frame: the photo is edited into new scenes, then animated.
          You approve the storyboard before anything is generated, and you see what each step costs.
        </p>
        <div className="row">
          <a href="#/create" className="btn btn-primary">
            Create an ad <ArrowRight size={18} aria-hidden="true" />
          </a>
          {recent[0] && (
            <a href={`#/job/${recent[0]}`} className="btn btn-secondary">
              Open your last ad
            </a>
          )}
        </div>
        <p className="muted small">
          Early version: generation needs an access code for now. Full 3-scene ads with voiceover and captions come
          next.
        </p>
      </section>

      <section className="section">
        <h2>How it works</h2>
        <ol className="steps">
          {STEPS.map((step, i) => {
            const Icon = step.icon;
            return (
              <li key={step.title} className="card">
                <span className="step-num">{i + 1}</span>
                <Icon size={22} aria-hidden="true" />
                <h3>{step.title}</h3>
                <p className="muted">{step.text}</p>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="section">
        <h2>The look we aim for</h2>
        <p className="muted">
          Illustrations of the UGC style, not made by this version of the app. Sample ads made by the app, with their
          real cost and quality scores, will replace them.
        </p>
        <div className="examples">
          {EXAMPLES.map((e) => (
            <img key={e.src} src={e.src} alt={e.alt} loading="lazy" />
          ))}
        </div>
      </section>
    </>
  );
}

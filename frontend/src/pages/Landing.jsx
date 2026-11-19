import { ArrowRight, Camera, CheckCircle2, Film, PenLine, Sparkles } from 'lucide-react';
import { recentJobs } from '../lib/api';

const STEPS = [
  { icon: Camera, title: 'Brief', text: 'One product photo, what it is and who it is for.' },
  { icon: PenLine, title: 'Storyboard', text: 'A 3-scene plan with hook ideas. You edit and approve it.' },
  { icon: Film, title: 'Generate', text: 'Your real product edited into a new scene, then animated.' },
  { icon: CheckCircle2, title: 'Review', text: 'Watch the result, with the cost of every step shown.' },
];

const REDUCED_MOTION =
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function showSteps() {
  document.getElementById('how')?.scrollIntoView({ behavior: REDUCED_MOTION ? 'auto' : 'smooth' });
}

export default function Landing() {
  const recent = recentJobs();
  return (
    <>
      <section className="lp-hero" aria-labelledby="lp-title">
        <div className="lp-copy">
          <p className="lp-badge">
            <Sparkles size={14} aria-hidden="true" /> Built on GPT-5 mini, Nano Banana and Kling 2.5
          </p>
          <h1 id="lp-title">
            Turn one product photo into a <span className="text-gradient"><span className="nowrap">ready-to-post</span> <span className="nowrap">video ad</span></span>
          </h1>
          <p className="lp-lead">
            Your real product stays in every frame. You approve the storyboard before anything is generated, and you
            see what each step costs.
          </p>
          <div className="lp-actions">
            <a href="#/create" className="btn btn-primary">
              Create an ad <ArrowRight size={18} aria-hidden="true" />
            </a>
            <button type="button" className="btn btn-secondary" onClick={showSteps}>
              See how it works
            </button>
          </div>
          {recent[0] && (
            <a href={`#/job/${recent[0]}`} className="lp-last">
              Open your last ad
            </a>
          )}
          <p className="muted small">Early access: generating needs an access code. The scenes here are examples.</p>
        </div>

        <figure className="lp-card lp-socks">
          <img src="/assets/landing/socks.webp" alt="A football team celebrating with a trophy, wearing grip socks" />
        </figure>
        <figure className="lp-card lp-tea">
          <img src="/assets/landing/tea.webp" alt="A woman drinking herbal tea on a herb farm" loading="lazy" />
        </figure>
        <figure className="lp-phone">
          <video
            src="/assets/landing/goal.mp4"
            poster="/assets/landing/goal-poster.webp"
            autoPlay={!REDUCED_MOTION}
            controls={REDUCED_MOTION}
            muted
            loop
            playsInline
            preload="metadata"
            aria-label="A footballer dribbles past a tackle, scores and points to the sky in front of the fans"
          />
        </figure>
        <figure className="lp-card lp-game">
          <img
            src="/assets/landing/game.webp"
            alt="Game art: a silver-haired hunter faces a lava monster"
            loading="lazy"
          />
          <figcaption className="lp-soon">Coming soon</figcaption>
        </figure>
      </section>

      <section id="how" className="lp-steps" aria-labelledby="how-title">
        <h2 id="how-title" className="lp-h2">
          How it works
        </h2>
        <ol className="lp-strip">
          {STEPS.map((step, i) => {
            const Icon = step.icon;
            return (
              <li key={step.title}>
                <span className="lp-step-icon">
                  <Icon size={20} aria-hidden="true" />
                </span>
                <h3>
                  <span className="muted">{i + 1}.</span> {step.title}
                </h3>
                <p className="muted small">{step.text}</p>
              </li>
            );
          })}
        </ol>
      </section>
    </>
  );
}

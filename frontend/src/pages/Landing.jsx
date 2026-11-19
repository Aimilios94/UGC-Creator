import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  Camera,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Film,
  PenLine,
  Sparkles,
} from 'lucide-react';
import { recentJobs } from '../lib/api';

const STEPS = [
  { icon: Camera, title: 'Brief', text: 'One product photo, what it is and who it is for.' },
  { icon: PenLine, title: 'Storyboard', text: 'A 3-scene plan with hook ideas. You edit and approve it.' },
  { icon: Film, title: 'Generate', text: 'Your real product edited into a new scene, then animated.' },
  { icon: CheckCircle2, title: 'Review', text: 'Watch the result, with the cost of every step shown.' },
];

const GALLERY = [
  {
    key: 'basketball',
    tag: 'Sport',
    title: 'Game-day basketball',
    text: 'A studio shot of the ball, turned into an arena dunk.',
    product: 'An orange basketball with a thin blue stripe, studio photo',
    scene: 'A player dunks the ball and the backboard glass shatters',
  },
  {
    key: 'keyboard',
    tag: 'Tech',
    title: 'Translucent keyboard',
    text: 'The keyboard on a desk at night, neon in the keys.',
    product: 'A mechanical keyboard with translucent keys, studio photo',
    scene: 'The keyboard on a desk by a rainy window with neon city light',
  },
  {
    key: 'hoodie',
    tag: 'Apparel',
    title: 'Anime art hoodie',
    text: 'A flat-lay of the print, worn on a neon street.',
    product: 'A black hoodie with a dark-fantasy anime back print, flat-lay',
    scene: 'Someone wearing the hoodie on a rain-wet neon street at night',
  },
];

function GalleryCard({ item }) {
  const [slide, setSlide] = useState(0);
  const track = useRef(null);
  const go = (i) => {
    const el = track.current;
    if (el) el.scrollTo({ left: i * el.clientWidth, behavior: REDUCED_MOTION ? 'auto' : 'smooth' });
  };
  const onScroll = () => {
    const el = track.current;
    if (el) setSlide(Math.round(el.scrollLeft / el.clientWidth));
  };
  const slides = [
    { src: `/assets/landing/${item.key}-product.webp`, alt: item.product, label: 'Product photo' },
    { src: `/assets/landing/${item.key}-scene.webp`, alt: item.scene, label: 'Ad scene' },
  ];
  return (
    <article className="gal-card">
      <div className="gal-media">
        <div className="gal-track" ref={track} onScroll={onScroll}>
          {slides.map((s) => (
            <img key={s.src} src={s.src} alt={s.alt} loading="lazy" />
          ))}
        </div>
        <span className="gal-tag">{item.tag}</span>
        <button
          type="button"
          className="gal-next"
          onClick={() => go(slide ? 0 : 1)}
          aria-label={slide ? 'Show the product photo' : 'Show the ad scene'}
        >
          {slide ? <ChevronLeft size={18} aria-hidden="true" /> : <ChevronRight size={18} aria-hidden="true" />}
        </button>
      </div>
      <div className="gal-steps" role="group" aria-label={`${item.title}: slides`}>
        {slides.map((s, i) => (
          <button
            key={s.label}
            type="button"
            className={i === slide ? 'active' : ''}
            aria-pressed={i === slide}
            onClick={() => go(i)}
          >
            <span>{i + 1}</span> {s.label}
          </button>
        ))}
      </div>
      <div className="gal-body">
        <h3>{item.title}</h3>
        <p className="muted small">{item.text}</p>
      </div>
    </article>
  );
}

const REDUCED_MOTION =
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const HERO_SLIDES = [
  { src: '/assets/landing/volley.webp', alt: 'A volleyball player leaps at the net to spike while her teammates watch' },
  { src: '/assets/landing/socks.webp', alt: 'A football team celebrating with a trophy, wearing grip socks' },
];

function HeroCarousel({ className, slides }) {
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (REDUCED_MOTION || paused) return undefined;
    const t = setInterval(() => setI((n) => (n + 1) % slides.length), 3300);
    return () => clearInterval(t);
  }, [paused, slides.length]);
  return (
    <figure
      className={`${className} hero-carousel`}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      {slides.map((s, n) => (
        <img key={s.src} src={s.src} alt={s.alt} className={n === i ? 'on' : ''} aria-hidden={n !== i} />
      ))}
      <div className="hero-dots">
        {slides.map((s, n) => (
          <button
            key={s.src}
            type="button"
            className={n === i ? 'active' : ''}
            aria-label={`Show picture ${n + 1} of ${slides.length}`}
            aria-pressed={n === i}
            onClick={() => setI(n)}
          />
        ))}
      </div>
    </figure>
  );
}

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

        <HeroCarousel className="lp-card lp-socks" slides={HERO_SLIDES} />
        <figure className="lp-card lp-hiker">
          <img
            src="/assets/landing/hiker.webp"
            alt="A hiker with a green backpack beside a mountain river, fog over the peaks"
            loading="lazy"
          />
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

      <section className="lp-gallery" aria-labelledby="gal-title">
        <h2 id="gal-title" className="lp-h2">
          See what&apos;s possible
        </h2>
        <p className="muted lp-sub">One product photo in, an ad scene out. Swipe or tap to compare. Examples.</p>
        <div className="gal-grid">
          {GALLERY.map((item) => (
            <GalleryCard key={item.key} item={item} />
          ))}
        </div>
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

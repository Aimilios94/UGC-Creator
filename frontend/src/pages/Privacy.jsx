import { useState } from 'react';
import { api } from '../lib/api.js';

const PROVIDERS = [
  {
    name: 'fal',
    what: 'Your product photo and the image and video prompts, to generate images and video clips.',
    where: 'United States (outside the EU).',
    notes: "We ask fal not to store requests, and fal's copies of generated files expire after one hour.",
    link: 'https://fal.ai/legal/privacy-policy',
  },
  {
    name: 'OpenAI',
    what: 'Your product photo and brief, to describe the product and write the storyboard; the voiceover lines, to make the AI voice.',
    where: 'United States (outside the EU).',
    notes: 'Sent through the OpenAI API with data sharing turned off for this project.',
    link: 'https://openai.com/policies/privacy-policy/',
  },
  {
    name: 'Neon (Databricks)',
    what: 'Your brief, the storyboard, job status and costs (the database).',
    where: 'AWS Europe Central 1, Frankfurt (EU).',
    link: 'https://www.databricks.com/legal/privacynotice',
  },
  {
    name: 'Google Cloud',
    what: 'The app server, and storage for your photo and the generated files (private, shared only through links that expire).',
    where: 'europe-west4, Netherlands (EU).',
    link: 'https://cloud.google.com/terms/cloud-privacy-notice',
  },
  {
    name: 'Sentry',
    what: 'Error reports when something breaks: the error, where in our code it happened, the page and IDs such as the ad ID. Never your brief, story, photos, email, IP address or location.',
    where: 'Frankfurt (EU).',
    notes: 'Only errors: no recordings of your screen, no tracking.',
    link: 'https://sentry.io/privacy/',
  },
  {
    name: 'Vercel',
    what: 'Hosts this website. It sees your IP address when you load the page.',
    where: 'Global edge network.',
    link: 'https://vercel.com/legal/privacy-notice',
  },
];

export default function Privacy() {
  return (
    <div className="page prose">
      <h1>Privacy notice</h1>
      <p className="muted">Last updated: 28 November 2026. The app is in early access.</p>

      <h2>What we collect</h2>
      <ul>
        <li>
          The product photo you upload, and any picture you upload for a scene. Location and camera data (EXIF/GPS) are
          removed when they arrive.
        </li>
        <li>
          The brief you type: product name, description, audience, offer, landing page, goal, theme, ad type, video
          length, and your own story with any style notes. Ads are grouped into campaigns, which keep a copy of the
          brief.
        </li>
        <li>
          Your brand kit, if you save one: logo (location and camera data removed, like photos), colours, font and tone
          of voice. It belongs to this browser only.
        </li>
        <li>
          What the app makes from them: the storyboard, images and video, and what each step cost. The History page
          lists the ads made in this browser.
        </li>
        <li>
          A random ID stored in your browser, so only this browser can open your ads. There is no account, no
          sign-in, no analytics and no tracking cookies.
        </li>
        <li>
          Fields marked &ldquo;Soon&rdquo; on the Create page (model preset, Hook Lab and email) are previews: what you
          type or pick there stays in your browser and is not sent to us.
        </li>
      </ul>

      <h2>People in photos</h2>
      <p>
        Upload photos of products, not people. If a person appears, you need their consent: the ad will show an
        AI-generated version of them.
      </p>

      <h2>Who processes your data</h2>
      <div className="providers">
        {PROVIDERS.map((p) => (
          <div key={p.name} className="card">
            <h3>{p.name}</h3>
            <p><strong>What:</strong> {p.what}</p>
            <p><strong>Where:</strong> {p.where}</p>
            {p.notes && <p className="muted">{p.notes}</p>}
            <a href={p.link} target="_blank" rel="noreferrer">Their privacy policy</a>
          </div>
        ))}
      </div>
      <p className="muted small">
        fal and OpenAI process data in the United States, so using the generator transfers your photo and brief
        outside the EU.
      </p>

      <h2>How long we keep it</h2>
      <p>
        Each ad, with its photos, pictures, clips and videos, is deleted 30 days after it was last changed. Your brand
        kit, logo and campaigns are deleted after 30 days without use. What each step cost is kept without the link to
        your ad, so the app's daily spending limit still adds up.
      </p>
      <DeleteMyData />

      <h2>AI-generated content</h2>
      <p>
        Everything this app generates is made by AI. When you post an ad, label it as AI-generated where the platform
        asks you to.
      </p>
    </div>
  );
}

function DeleteMyData() {
  const [step, setStep] = useState('idle'); // idle | confirm | busy | done
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  async function run() {
    setStep('busy');
    setError('');
    try {
      setResult(await api.deleteMyData());
      setStep('done');
    } catch (e) {
      setError(e.message);
      setStep('confirm');
    }
  }

  return (
    <div className="card delete-data">
      <h3>Delete my data</h3>
      <p>
        Deletes every ad made in this browser (photos, pictures, clips and videos), your brand kit, logo and campaigns,
        at once. It cannot be undone. Other browsers are not affected.
      </p>
      {step === 'idle' && (
        <button type="button" className="btn btn-secondary" onClick={() => setStep('confirm')}>
          Delete my data
        </button>
      )}
      {(step === 'confirm' || step === 'busy') && (
        <div className="row-actions">
          <button type="button" className="btn btn-primary danger" onClick={run} disabled={step === 'busy'}>
            {step === 'busy' ? 'Deleting…' : 'Yes, delete everything'}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setStep('idle')} disabled={step === 'busy'}>
            Cancel
          </button>
        </div>
      )}
      {error && <p className="error small" role="alert">{error}</p>}
      {step === 'done' && result && (
        <p className="notice" role="status">
          Deleted {result.jobs_deleted} {result.jobs_deleted === 1 ? 'ad' : 'ads'}
          {result.brand_kits_deleted ? ', your brand kit' : ''}
          {result.campaigns_deleted ? ` and ${result.campaigns_deleted} ${result.campaigns_deleted === 1 ? 'campaign' : 'campaigns'}` : ''}.
          {result.kept_busy ? ' One ad started while this ran and was kept: delete again when it is finished.' : ''}
        </p>
      )}
    </div>
  );
}

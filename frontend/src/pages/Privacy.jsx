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
    what: 'Your product photo and brief, to describe the product and write the storyboard.',
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
      <p className="muted">Last updated: 18 November 2026. This is a portfolio project in early access.</p>

      <h2>What we collect</h2>
      <ul>
        <li>The product photo you upload. Location and camera data (EXIF/GPS) are removed when it arrives.</li>
        <li>The brief you type: product name, description, audience, offer and landing page.</li>
        <li>What the app makes from them: the storyboard, images and video, and what each step cost.</li>
        <li>
          A random ID stored in your browser, so only this browser can open your ads. There is no account, no
          sign-in, no analytics and no tracking cookies.
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
        Coming in the next version: uploads and generated files are deleted automatically after 30 days, and a
        &ldquo;Delete my data&rdquo; button removes your ads at once. Until then, generation is limited to people with an
        access code.
      </p>

      <h2>AI-generated content</h2>
      <p>
        Everything this app generates is made by AI. When you post an ad, label it as AI-generated where the platform
        asks you to.
      </p>
    </div>
  );
}

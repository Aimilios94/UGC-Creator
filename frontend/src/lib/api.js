// API client. One place for the base URL, the browser session ID and the access code.
//
// No sign-in: the browser creates a random session ID once and sends it with every
// request; a job can only be opened from the session that created it.

const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

// Full URL of an API path (for audio previews played straight from the API).
export const apiUrl = (path) => `${BASE}${path}`;

let memorySession = null;
let memoryCode = '';

function randomId() {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function sessionId() {
  try {
    let id = localStorage.getItem('ugc.session');
    if (!id) {
      id = randomId();
      localStorage.setItem('ugc.session', id);
    }
    return id;
  } catch {
    memorySession = memorySession || randomId();
    return memorySession;
  }
}

export function getAccessCode() {
  try {
    return sessionStorage.getItem('ugc.access') || memoryCode;
  } catch {
    return memoryCode;
  }
}

export function setAccessCode(code) {
  memoryCode = code;
  try {
    sessionStorage.setItem('ugc.access', code);
  } catch {
    /* private mode: keep it in memory */
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = 'GET', json, form } = {}) {
  const headers = { 'X-Session-Id': sessionId() };
  const code = getAccessCode();
  if (code) headers['X-Access-Code'] = code;
  let body;
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body });
  } catch {
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : 'Something went wrong. Please try again.';
    throw new ApiError(detail, res.status);
  }
  return data;
}

export const api = {
  config: () => request('/config'),
  checkAccess: (code) => request('/access/check', { method: 'POST', json: { code } }),
  // options: { campaignId, campaignName, useBrandKit }
  createJob: (brief, photo, options = {}) => {
    const form = new FormData();
    form.append('brief', JSON.stringify(brief));
    form.append('photo', photo);
    if (options.campaignId) form.append('campaign_id', options.campaignId);
    if (options.campaignName) form.append('campaign_name', options.campaignName);
    form.append('use_brand_kit', options.useBrandKit ? 'true' : 'false');
    return request('/jobs', { method: 'POST', form });
  },
  campaigns: () => request('/campaigns'),
  getBrandKit: () => request('/brand-kit'),
  saveBrandKit: (kit) => request('/brand-kit', { method: 'PUT', json: kit }),
  uploadLogo: (file) => {
    const form = new FormData();
    form.append('logo', file);
    return request('/brand-kit/logo', { method: 'POST', form });
  },
  getJob: (id) => request(`/jobs/${encodeURIComponent(id)}`),
  saveStoryboard: (id, storyboard) =>
    request(`/jobs/${encodeURIComponent(id)}/storyboard`, { method: 'PUT', json: storyboard }),
  approve: (id, mode = 'images') =>
    request(`/jobs/${encodeURIComponent(id)}/approve`, { method: 'POST', json: { mode } }),
  story: (id, story) => request(`/jobs/${encodeURIComponent(id)}/story`, { method: 'POST', json: { story } }),
  uploadSceneImage: (id, idx, file) => {
    const form = new FormData();
    form.append('image', file);
    return request(`/jobs/${encodeURIComponent(id)}/scenes/${idx}/image`, { method: 'POST', form });
  },
  makeVideo: (id, storyboard) =>
    request(`/jobs/${encodeURIComponent(id)}/video`, { method: 'POST', json: storyboard ?? null }),
  retry: (id) => request(`/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  setSound: (id, sound) => request(`/jobs/${encodeURIComponent(id)}/sound`, { method: 'PUT', json: sound }),
  voices: () => request('/voices'),
  music: () => request('/music'),
};

export function rememberJob(id) {
  try {
    const list = JSON.parse(localStorage.getItem('ugc.jobs') || '[]').filter((j) => j !== id);
    localStorage.setItem('ugc.jobs', JSON.stringify([id, ...list].slice(0, 20)));
  } catch {
    /* not essential */
  }
}

export function recentJobs() {
  try {
    return JSON.parse(localStorage.getItem('ugc.jobs') || '[]');
  } catch {
    return [];
  }
}

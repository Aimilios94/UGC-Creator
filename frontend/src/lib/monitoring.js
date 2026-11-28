// Sentry error monitoring (M2 item 5), on only when VITE_SENTRY_DSN is set at build time.
//
// Privacy first (docs/PRIVACY.md): only the error type, the stack trace and the page path go out.
// SDK 11 collects personal data by default, so every category is switched off here, and
// scrubEvent runs on every event and breadcrumb before it leaves: no request data, no user,
// emails, web addresses and the access code replaced, long texts cut short. No tracing,
// no session replay, no logs.
import * as Sentry from '@sentry/react';
import { getAccessCode } from './api.js';

const DSN = import.meta.env.VITE_SENTRY_DSN || '';
export const MAX_TEXT = 300;
const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g;
const URL_RX = /\b(?:https?|ftp):\/\/[^\s'"<>]+|\bwww\.[^\s'"<>]+/gi;
// Code locations: never user text, and Sentry needs them as they are.
const KEEP = new Set(['filename', 'abs_path', 'module', 'function', 'type', 'event_id', 'timestamp',
  'level', 'logger', 'release', 'environment', 'platform', 'category', 'mechanism']);

export function scrubText(text, secrets = []) {
  let out = String(text);
  for (const s of secrets) if (s && s.length >= 4) out = out.split(s).join('[secret]');
  out = out.replace(EMAIL, '[email]').replace(URL_RX, '[url]');
  return out.length <= MAX_TEXT ? out : `${out.slice(0, MAX_TEXT)}…[cut]`;
}

function walk(value, secrets, key = '') {
  if (typeof value === 'string') return KEEP.has(key) ? value : scrubText(value, secrets);
  if (Array.isArray(value)) return value.map((v) => walk(v, secrets, key));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, walk(v, secrets, k)]));
  }
  return value;
}

// Only the path of a web address: no host, no query string.
const pathOnly = (url) => String(url || '').replace(/^[a-z]+:\/\/[^/]+/i, '').split('?')[0];

export function scrubEvent(event, secrets = []) {
  const out = { ...event };
  if (out.request) out.request = { url: pathOnly(out.request.url) };
  delete out.user;
  delete out.extra;
  return walk(out, secrets);
}

export function scrubBreadcrumb(crumb, secrets = []) {
  const out = { ...crumb };
  if (out.data?.url) out.data = { ...out.data, url: pathOnly(out.data.url) };
  if (out.data?.from) out.data = { ...out.data, from: pathOnly(out.data.from), to: pathOnly(out.data.to) };
  return walk(out, secrets);
}

export function initMonitoring() {
  if (!DSN) return false;
  const secrets = () => [getAccessCode()];
  Sentry.init({
    dsn: DSN,
    release: `ugc-web@${import.meta.env.VITE_APP_VERSION || 'dev'}`,
    environment: import.meta.env.MODE === 'production' ? 'prod' : 'local',
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: false,
      httpBodies: [],
      urlQueryParams: false,
      genAI: { inputs: false, outputs: false },
      stackFrameVariables: false,
    },
    tracesSampleRate: 0,
    maxBreadcrumbs: 30,
    beforeSend: (event) => scrubEvent(event, secrets()),
    beforeBreadcrumb: (crumb) => scrubBreadcrumb(crumb, secrets()),
  });
  Sentry.setTag('component', 'web');
  return true;
}

// React 19 root error hooks: report, then let React do what it does by default.
export const rootErrorHooks = DSN
  ? {
      onUncaughtError: Sentry.reactErrorHandler(),
      onCaughtError: Sentry.reactErrorHandler(),
      onRecoverableError: Sentry.reactErrorHandler(),
    }
  : {};

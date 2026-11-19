// Money is shown in EUR by default; USD is a display option under Advanced settings.
// The API sends both values (converted at one app-wide rate), so switching is instant.

export function getCurrency() {
  try {
    return localStorage.getItem('ugc.currency') === 'USD' ? 'USD' : 'EUR';
  } catch {
    return 'EUR';
  }
}

export function setCurrency(cur) {
  try {
    localStorage.setItem('ugc.currency', cur);
  } catch {
    /* per-viewer convenience only */
  }
  window.dispatchEvent(new Event('ugc-currency'));
}

export function formatMoney(money, currency) {
  if (!money) return '–';
  const value = currency === 'USD' ? money.usd : money.eur;
  return new Intl.NumberFormat('en-IE', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: value < 0.1 ? 3 : 2,
  }).format(value);
}

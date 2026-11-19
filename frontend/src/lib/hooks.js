import { useEffect, useState } from 'react';
import { getCurrency } from './money';

export function useHashRoute() {
  const read = () => window.location.hash.replace(/^#/, '') || '/';
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => {
      setRoute(read());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export function useCurrency() {
  const [currency, setCur] = useState(getCurrency);
  useEffect(() => {
    const onChange = () => setCur(getCurrency());
    window.addEventListener('ugc-currency', onChange);
    return () => window.removeEventListener('ugc-currency', onChange);
  }, []);
  return currency;
}

export function navigate(path) {
  window.location.hash = path;
}

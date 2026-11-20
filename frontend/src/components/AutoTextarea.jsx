import { useLayoutEffect, useRef } from 'react';

// A textarea that grows with its text, so a whole story or shot list can be read without scrolling.
export default function AutoTextarea({ value, minRows = 2, ...props }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [value]);
  return <textarea ref={ref} rows={minRows} value={value} {...props} className={`auto-grow ${props.className || ''}`} />;
}

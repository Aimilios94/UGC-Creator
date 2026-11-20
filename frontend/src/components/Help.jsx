import { useId } from 'react';
import { Info } from 'lucide-react';

export function Help({ text, label = 'More information' }) {
  const id = useId();
  return (
    <span className="help" tabIndex={0} aria-label={label} aria-describedby={id}>
      <Info size={14} aria-hidden="true" />
      <span role="tooltip" id={id} className="tip">
        {text}
      </span>
    </span>
  );
}

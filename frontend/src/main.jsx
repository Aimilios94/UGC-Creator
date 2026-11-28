import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import { initMonitoring, rootErrorHooks } from './lib/monitoring.js';
import './styles/global.css';
import './styles/app.css';

initMonitoring();

ReactDOM.createRoot(document.getElementById('root'), rootErrorHooks).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import './index.css';
import { BotProvider } from './bot/BotContext.tsx';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BotProvider>
      <App />
    </BotProvider>
  </StrictMode>,
);

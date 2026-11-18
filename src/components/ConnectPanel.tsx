import { useEffect, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { KeyRound, Loader2, QrCode, RefreshCw, ShieldAlert } from 'lucide-react';
import type { Instance } from '../../shared/types';
import { api } from '../lib/api';
import { useAppStore } from '../state/AppStore';
import { Button, Field, inputClass } from './ui';

/**
 * Shows the real QR payload from Baileys, or lets the user link with an
 * 8-character pairing code. The QR is re-fetched whenever the server falls
 * back to a new one (WhatsApp rotates them every ~20s).
 */
export function ConnectPanel({ instance }: { instance: Instance }) {
  const { actions, notify } = useAppStore();
  const [qr, setQr] = useState<string | null>(instance.qr ?? null);
  const [phone, setPhone] = useState('');
  const [pairingCode, setPairingCode] = useState<string | null>(instance.pairingCode ?? null);
  const [requesting, setRequesting] = useState(false);
  const [mode, setMode] = useState<'qr' | 'code'>('qr');

  useEffect(() => {
    setQr(instance.qr ?? null);
    setPairingCode(instance.pairingCode ?? null);
  }, [instance.qr, instance.pairingCode]);

  useEffect(() => {
    if (instance.status !== 'qr') return;
    let cancelled = false;
    const tick = async () => {
      try {
        const result = await api.getQr(instance.id);
        if (!cancelled) setQr(result.qr);
      } catch {
        /* transient — next tick retries */
      }
    };
    void tick();
    const interval = window.setInterval(tick, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [instance.id, instance.status]);

  const requestCode = async () => {
    setRequesting(true);
    try {
      const result = await api.requestPairingCode(instance.id, phone);
      setPairingCode(result.pairingCode);
      notify('Pairing code ready — enter it on your phone', 'success');
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Could not request pairing code', 'error');
    } finally {
      setRequesting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-1 rounded-lg border border-white/10 bg-black/30 p-1">
        <button
          type="button"
          onClick={() => setMode('qr')}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            mode === 'qr' ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <QrCode className="h-3.5 w-3.5" /> QR code
        </button>
        <button
          type="button"
          onClick={() => setMode('code')}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            mode === 'code' ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <KeyRound className="h-3.5 w-3.5" /> Phone number
        </button>
      </div>

      {mode === 'qr' ? (
        qr ? (
          <div className="flex flex-col items-center gap-3">
            <div className="rounded-xl bg-white p-3 shadow-lg">
              <QRCodeSVG value={qr} size={188} level="M" marginSize={0} />
            </div>
            <ol className="space-y-1 text-xs text-slate-400">
              <li>1. Open WhatsApp on your phone</li>
              <li>2. Settings → Linked devices → Link a device</li>
              <li>3. Point the camera at this code</li>
            </ol>
            <p className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <RefreshCw className="h-3 w-3 animate-spin" /> Refreshes automatically
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 py-8 text-slate-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <p className="text-xs">Waiting for WhatsApp to issue a QR code…</p>
          </div>
        )
      ) : (
        <div className="flex flex-col gap-3">
          {pairingCode ? (
            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4 text-center">
              <p className="text-[11px] uppercase tracking-wider text-emerald-400/80">
                Pairing code
              </p>
              <p className="mt-1 font-mono text-2xl tracking-[0.2em] text-white">{pairingCode}</p>
            </div>
          ) : null}
          <Field label="WhatsApp number" hint="Include the country code, digits only.">
            <input
              className={inputClass}
              inputMode="tel"
              placeholder="923001234567"
              value={phone}
              onChange={(event) => setPhone(event.target.value.replace(/[^\d+\s-]/g, ''))}
            />
          </Field>
          <Button variant="primary" onClick={requestCode} loading={requesting} disabled={!phone}>
            <KeyRound className="h-3.5 w-3.5" /> Get pairing code
          </Button>
          <p className="text-[11px] text-slate-500">
            On your phone: Linked devices → Link with phone number, then type the code above.
          </p>
        </div>
      )}

      <div className="flex items-start gap-2 rounded-lg border border-amber-500/15 bg-amber-500/5 p-2.5 text-[11px] text-amber-300/80">
        <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Credentials are stored server-side in <code>data/sessions/&lt;id&gt;</code>. Anyone with
          access to this panel controls that WhatsApp account.
        </span>
      </div>

      <Button variant="ghost" size="sm" onClick={() => actions.stop(instance.id)}>
        Cancel and stop
      </Button>
    </div>
  );
}

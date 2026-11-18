import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import type { Instance, InstanceConfig } from '../../shared/types';
import { useAppStore } from '../state/AppStore';
import { Button, Card, Field, inputClass, SectionTitle, Toggle } from './ui';

function parseNumbers(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\s,;\n]+/)
        .map((entry) => entry.replace(/\D/g, ''))
        .filter((entry) => entry.length >= 8 && entry.length <= 15),
    ),
  );
}

export function ConfigPanel({ instance }: { instance: Instance }) {
  const { actions } = useAppStore();
  const [name, setName] = useState(instance.name);
  const [config, setConfig] = useState<InstanceConfig>(instance.config);
  const [allowed, setAllowed] = useState(instance.config.allowedNumbers.join(', '));
  const [blocked, setBlocked] = useState(instance.config.blockedNumbers.join(', '));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setName(instance.name);
    setConfig(instance.config);
    setAllowed(instance.config.allowedNumbers.join(', '));
    setBlocked(instance.config.blockedNumbers.join(', '));
  }, [instance]);

  const dirty =
    name !== instance.name ||
    JSON.stringify({ ...config, allowedNumbers: [], blockedNumbers: [] }) !==
      JSON.stringify({ ...instance.config, allowedNumbers: [], blockedNumbers: [] }) ||
    allowed !== instance.config.allowedNumbers.join(', ') ||
    blocked !== instance.config.blockedNumbers.join(', ');

  const save = async () => {
    setSaving(true);
    await actions.saveConfig(instance.id, {
      name: name.trim() || instance.name,
      config: {
        ...config,
        allowedNumbers: parseNumbers(allowed),
        blockedNumbers: parseNumbers(blocked),
      },
    });
    setSaving(false);
  };

  return (
    <Card className="flex flex-col gap-4 p-4">
      <SectionTitle title="Behaviour" hint="How this bot reacts to incoming chats." />

      <Field label="Display name">
        <input
          className={inputClass}
          value={name}
          maxLength={60}
          onChange={(event) => setName(event.target.value)}
        />
      </Field>

      <Field label="Command prefix" hint="1–3 characters, e.g. ! or . or /">
        <input
          className={`${inputClass} w-24 font-mono`}
          value={config.commandPrefix}
          maxLength={3}
          onChange={(event) =>
            setConfig((prev) => ({ ...prev, commandPrefix: event.target.value }))
          }
        />
      </Field>

      <div className="grid gap-2 sm:grid-cols-2">
        <Toggle
          label="Reply in groups"
          checked={config.respondToGroups}
          onChange={(value) => setConfig((prev) => ({ ...prev, respondToGroups: value }))}
        />
        <Toggle
          label="Reply in direct chats"
          checked={config.respondToDms}
          onChange={(value) => setConfig((prev) => ({ ...prev, respondToDms: value }))}
        />
        <Toggle
          label="Mark messages as read"
          checked={config.autoReadMessages}
          onChange={(value) => setConfig((prev) => ({ ...prev, autoReadMessages: value }))}
        />
      </div>

      <Field
        label="Allowlist (optional)"
        hint="Digits only, comma separated. Empty means everyone can use commands."
      >
        <textarea
          className={`${inputClass} min-h-[60px] font-mono text-xs`}
          placeholder="923001234567, 447700900123"
          value={allowed}
          onChange={(event) => setAllowed(event.target.value)}
        />
      </Field>

      <Field label="Blocklist" hint="These numbers are always ignored.">
        <textarea
          className={`${inputClass} min-h-[60px] font-mono text-xs`}
          placeholder="923009999999"
          value={blocked}
          onChange={(event) => setBlocked(event.target.value)}
        />
      </Field>

      <div className="flex justify-end border-t border-white/[0.07] pt-3">
        <Button variant="primary" size="sm" onClick={save} loading={saving} disabled={!dirty}>
          <Save className="h-3.5 w-3.5" /> Save changes
        </Button>
      </div>
    </Card>
  );
}

import { useState } from 'react';
import { Plus, RotateCcw, Trash2 } from 'lucide-react';
import { DEFAULT_COMMANDS, type CommandRule, type Instance } from '../../shared/types';
import { useAppStore } from '../state/AppStore';
import { Button, Card, inputClass, SectionTitle, Toggle } from './ui';

const PLACEHOLDERS = [
  '{{sender}}',
  '{{args}}',
  '{{instance}}',
  '{{uptime}}',
  '{{received}}',
  '{{prefix}}',
  '{{commands}}',
];

export function CommandEditor({ instance }: { instance: Instance }) {
  const { actions, notify } = useAppStore();
  const [draft, setDraft] = useState<CommandRule[]>(instance.commands);
  const [saving, setSaving] = useState(false);

  const dirty = JSON.stringify(draft) !== JSON.stringify(instance.commands);
  const prefix = instance.config.commandPrefix;

  const update = (index: number, patch: Partial<CommandRule>) => {
    setDraft((prev) => prev.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));
  };

  const addRule = () => {
    const name = `cmd${draft.length + 1}`;
    setDraft((prev) => [...prev, { name, response: 'Hello {{sender}} 👋', enabled: true }]);
  };

  const save = async () => {
    const invalid = draft.find((rule) => !rule.name.trim() || !rule.response.trim());
    if (invalid) {
      notify('Every command needs a name and a response', 'error');
      return;
    }
    setSaving(true);
    await actions.saveConfig(instance.id, { commands: draft });
    setSaving(false);
  };

  return (
    <Card className="flex flex-col gap-4 p-4">
      <SectionTitle
        title="Commands"
        hint={`Messages starting with "${prefix}" trigger these.`}
        action={
          <Button size="sm" onClick={addRule}>
            <Plus className="h-3.5 w-3.5" /> Add
          </Button>
        }
      />

      <div className="flex flex-col gap-2">
        {draft.length === 0 && (
          <p className="rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-xs text-slate-500">
            No commands yet — this bot will stay silent.
          </p>
        )}
        {draft.map((rule, index) => (
          <div
            key={index}
            className="flex flex-col gap-2 rounded-lg border border-white/[0.07] bg-black/20 p-3"
          >
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-slate-500">{prefix}</span>
              <input
                value={rule.name}
                onChange={(event) =>
                  update(index, {
                    name: event.target.value.toLowerCase().replace(/\s+/g, ''),
                  })
                }
                placeholder="command"
                aria-label={`Command ${index + 1} name`}
                className={`${inputClass} h-8 py-1 font-mono text-xs`}
              />
              <Toggle
                checked={rule.enabled}
                onChange={(value) => update(index, { enabled: value })}
                label=""
              />
              <button
                type="button"
                aria-label={`Remove ${rule.name}`}
                onClick={() => setDraft((prev) => prev.filter((_, i) => i !== index))}
                className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-rose-500/10 hover:text-rose-300"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
            <textarea
              value={rule.response}
              onChange={(event) => update(index, { response: event.target.value })}
              rows={2}
              placeholder="Reply text…"
              aria-label={`Response for ${rule.name}`}
              className={`${inputClass} resize-y font-mono text-xs`}
            />
            <div className="flex flex-wrap items-center gap-1.5">
              <TestToggle
                exact={Boolean(rule.exact)}
                onChange={(value) => update(index, { exact: value })}
              />
              {PLACEHOLDERS.map((token) => (
                <button
                  key={token}
                  type="button"
                  onClick={() => update(index, { response: `${rule.response}${token}` })}
                  className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-slate-500 transition-colors hover:border-emerald-500/30 hover:text-emerald-300"
                >
                  {token}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-white/[0.07] pt-3">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setDraft(structuredClone(DEFAULT_COMMANDS))}
        >
          <RotateCcw className="h-3.5 w-3.5" /> Reset to defaults
        </Button>
        <div className="flex items-center gap-2">
          {dirty && (
            <Button size="sm" variant="ghost" onClick={() => setDraft(instance.commands)}>
              Discard
            </Button>
          )}
          <Button size="sm" variant="primary" onClick={save} loading={saving} disabled={!dirty}>
            Save commands
          </Button>
        </div>
      </div>
    </Card>
  );
}

function TestToggle({ exact, onChange }: { exact: boolean; onChange: (value: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!exact)}
      className={`rounded border px-1.5 py-0.5 text-[10px] transition-colors ${
        exact
          ? 'border-sky-500/40 bg-sky-500/10 text-sky-300'
          : 'border-white/10 text-slate-500 hover:text-slate-300'
      }`}
      title="Match this word without any prefix"
    >
      exact match
    </button>
  );
}

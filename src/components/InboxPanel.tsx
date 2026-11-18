import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowDownLeft,
  ArrowUpRight,
  Clock,
  MessageSquare,
  Send,
  Users,
} from 'lucide-react';
import type { Conversation, InboxMessage, Instance } from '../../shared/types';
import { api, subscribeToInbox } from '../lib/api';
import { formatRelative, formatTime } from '../lib/format';
import { useAppStore } from '../state/AppStore';
import { cn } from '../lib/utils';
import { Button, Card, EmptyState, inputClass } from './ui';

/**
 * Two-pane inbox: chat list on the left, transcript + composer on the right.
 * Every send goes through the server-side throttle, so the composer shows the
 * remaining quota and explains any wait instead of silently hanging.
 */
export function InboxPanel({ instance }: { instance: Instance }) {
  const { notify } = useAppStore();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [throttle, setThrottle] = useState({ remaining: 0, limit: 0, minGapMs: 0 });
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [newChat, setNewChat] = useState('');
  const [loading, setLoading] = useState(true);
  const transcript = useRef<HTMLDivElement>(null);

  const loadConversations = useCallback(async () => {
    try {
      const result = await api.getConversations(instance.id);
      setConversations(result.conversations);
      setSelected((current) => current ?? result.conversations[0]?.chatJid ?? null);
    } catch {
      /* the parent view already surfaces connection errors */
    } finally {
      setLoading(false);
    }
  }, [instance.id]);

  const loadMessages = useCallback(
    async (chatJid: string | null) => {
      try {
        const result = await api.getMessages(instance.id, { chatJid: chatJid ?? undefined });
        setMessages(result.messages);
        setThrottle(result.throttle);
      } catch {
        /* transient */
      }
    },
    [instance.id],
  );

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    void loadMessages(selected);
    if (selected) void api.markConversationRead(instance.id, selected).catch(() => {});
  }, [instance.id, selected, loadMessages]);

  // Live updates: refetch the transcript whenever the server signals activity.
  useEffect(() => {
    const unsubscribe = subscribeToInbox(instance.id, () => {
      void loadConversations();
      void loadMessages(selected);
    });
    return unsubscribe;
  }, [instance.id, selected, loadConversations, loadMessages]);

  useEffect(() => {
    const node = transcript.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages]);

  const canSend = instance.status === 'connected';
  const recipient = useMemo(() => selected ?? newChat.trim(), [selected, newChat]);

  const send = async () => {
    if (!recipient || !text.trim()) return;
    setSending(true);
    try {
      const result = await api.sendMessage(instance.id, recipient, text.trim());
      setText('');
      if (result.waitedMs > 500) {
        notify(
          `Queued for ${Math.round(result.waitedMs / 1000)}s by the outbound throttle`,
          'info',
        );
      }
      await loadMessages(selected);
      await loadConversations();
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Could not send the message', 'error');
    } finally {
      setSending(false);
    }
  };

  const clearHistory = async () => {
    try {
      await api.clearMessages(instance.id);
      setMessages([]);
      setConversations([]);
      setSelected(null);
      notify('Inbox cleared', 'success');
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Could not clear the inbox', 'error');
    }
  };

  return (
    <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[260px_1fr]">
      <Card className="flex min-h-0 flex-col p-3">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold text-white">Chats</h3>
          <button
            onClick={clearHistory}
            className="text-[10px] uppercase tracking-wider text-slate-500 transition-colors hover:text-rose-300"
          >
            Clear
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {loading && <p className="px-1 py-2 text-xs text-slate-600">Loading…</p>}
          {!loading && conversations.length === 0 && (
            <p className="px-1 py-2 text-xs text-slate-600">
              No conversations yet. Messages will appear here once this bot receives traffic.
            </p>
          )}
          {conversations.map((conversation) => (
            <button
              key={conversation.chatJid}
              onClick={() => {
                setSelected(conversation.chatJid);
                setNewChat('');
              }}
              className={cn(
                'flex w-full flex-col gap-0.5 rounded-lg px-2 py-1.5 text-left transition-colors',
                selected === conversation.chatJid
                  ? 'bg-emerald-500/10 ring-1 ring-emerald-500/20'
                  : 'hover:bg-white/5',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1 truncate text-xs text-slate-200">
                  {conversation.isGroup ? (
                    <Users className="h-3 w-3 shrink-0 text-slate-500" />
                  ) : null}
                  <span className="truncate">{conversation.chatName}</span>
                </span>
                {conversation.unread > 0 && (
                  <span className="shrink-0 rounded-full bg-emerald-500 px-1.5 text-[10px] font-semibold text-black">
                    {conversation.unread}
                  </span>
                )}
              </div>
              <span className="truncate text-[11px] text-slate-500">
                {conversation.lastMessage}
              </span>
              <span className="text-[10px] text-slate-600">
                {formatRelative(conversation.lastTs)}
              </span>
            </button>
          ))}
        </div>
      </Card>

      <Card className="flex min-h-0 flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-2.5">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-white">
              {selected
                ? (conversations.find((c) => c.chatJid === selected)?.chatName ?? selected)
                : 'New message'}
            </p>
            <p className="truncate font-mono text-[10px] text-slate-500">
              {selected ?? recipient ?? '—'}
            </p>
          </div>
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
            <Clock className="h-3 w-3" />
            {throttle.remaining}/{throttle.limit} left this minute
          </div>
        </div>

        {!selected && (
          <div className="border-b border-white/[0.07] px-4 py-2">
            <input
              value={newChat}
              onChange={(event) => setNewChat(event.target.value)}
              placeholder="New chat: +92 300 1234567 or 123456@g.us"
              aria-label="New chat recipient"
              className={`${inputClass} text-xs`}
            />
          </div>
        )}

        <div
          ref={transcript}
          className="min-h-0 flex-1 space-y-2 overflow-y-auto bg-[radial-gradient(circle_at_50%_0%,rgba(16,185,129,0.04),transparent)] px-4 py-3"
        >
          {messages.length === 0 ? (
            <EmptyState
              icon={<MessageSquare className="h-7 w-7" />}
              title="No messages"
              description={
                canSend
                  ? 'Send the first message below, or wait for this bot to receive one.'
                  : 'Start this bot and link a device before sending messages.'
              }
            />
          ) : (
            messages.map((message) => <Bubble key={message.id} message={message} />)
          )}
        </div>

        <div className="border-t border-white/[0.07] p-3">
          {!canSend && (
            <p className="mb-2 flex items-center gap-1.5 rounded-md border border-amber-500/20 bg-amber-500/5 px-2 py-1 text-[11px] text-amber-300/90">
              <AlertCircle className="h-3 w-3 shrink-0" /> This bot is not connected. Start it to
              send messages.
            </p>
          )}
          <div className="flex items-end gap-2">
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
              rows={2}
              maxLength={4096}
              placeholder={recipient ? 'Type a message… (Enter to send)' : 'Pick a chat first'}
              aria-label="Message text"
              disabled={!canSend}
              className={`${inputClass} min-h-[44px] resize-y text-sm disabled:opacity-50`}
            />
            <Button
              variant="primary"
              onClick={send}
              loading={sending}
              disabled={!canSend || !recipient || !text.trim()}
            >
              <Send className="h-3.5 w-3.5" /> Send
            </Button>
          </div>
          <p className="mt-1.5 flex items-center justify-between text-[10px] text-slate-600">
            <span>
              Outbound messages are paced to protect the number ({throttle.minGapMs}ms minimum gap).
            </span>
            <span>{text.length}/4096</span>
          </p>
        </div>
      </Card>
    </div>
  );
}

function Bubble({ message }: { message: InboxMessage }) {
  const outgoing = message.direction === 'out';
  return (
    <div className={cn('flex', outgoing ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[80%] rounded-xl px-3 py-1.5 text-xs',
          outgoing
            ? 'bg-emerald-500/15 text-emerald-50 ring-1 ring-emerald-500/20'
            : 'bg-white/5 text-slate-200 ring-1 ring-white/5',
        )}
      >
        <div className="mb-0.5 flex items-center gap-1 text-[10px] text-slate-500">
          {outgoing ? (
            <ArrowUpRight className="h-2.5 w-2.5" />
          ) : (
            <ArrowDownLeft className="h-2.5 w-2.5" />
          )}
          <span className="truncate">{outgoing ? 'Bot' : message.senderName}</span>
          {message.origin === 'command' && (
            <span className="rounded bg-black/30 px-1 text-[9px] uppercase">command</span>
          )}
          <span className="ml-auto pl-2 font-mono">{formatTime(message.ts)}</span>
        </div>
        <p className="whitespace-pre-wrap break-words">{message.text || `[${message.kind}]`}</p>
      </div>
    </div>
  );
}

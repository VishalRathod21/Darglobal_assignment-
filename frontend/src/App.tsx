import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, clearSession, getIngestionStatus, loadHistory, sendQuestion } from "./api";
import { Composer } from "./components/Composer";
import { Message, TypingIndicator } from "./components/Message";
import { Sidebar } from "./components/Sidebar";
import { newSessionId, readConversations, writeConversations } from "./storage";
import type { ChatMessage, Conversation, IngestionStatus } from "./types";

const SUGGESTIONS = [
  "Which projects does DarGlobal have in Oman?",
  "What amenities does Trump Tower Jeddah offer?",
  "What did DarGlobal announce about Jeddah in November 2026?",
  "Show me 3-bedroom apartments for sale in Riyadh under SAR 800,000",
  "What is DG1 and where is it located?",
  "Why invest with DarGlobal?",
];

let messageCounter = 0;
const nextId = () => `m${++messageCounter}`;

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>(readConversations);
  const [sessionId, setSessionId] = useState<string>(() => readConversations()[0]?.id ?? newSessionId());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [status, setStatus] = useState<IngestionStatus | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const activeSession = useRef(sessionId);
  activeSession.current = sessionId;

  useEffect(() => {
    getIngestionStatus().then(setStatus).catch(() => setStatus({}));
  }, []);

  // Restore the thread whenever the active conversation changes.
  useEffect(() => {
    const known = readConversations().some((conversation) => conversation.id === sessionId);
    if (!known) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setRestoring(true);
    loadHistory(sessionId)
      .then((history) => !cancelled && setMessages(history))
      .catch(() => !cancelled && setBanner("Couldn't load this conversation. It may have expired on the server."))
      .finally(() => !cancelled && setRestoring(false));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    // Not on the empty state: scrolling there would push the heading off small screens.
    if (messages.length > 0) bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const rememberConversation = useCallback((id: string, firstQuestion: string) => {
    setConversations((current) => {
      const existing = current.find((conversation) => conversation.id === id);
      const entry: Conversation = existing
        ? { ...existing, updatedAt: Date.now() }
        : { id, title: firstQuestion.slice(0, 60), updatedAt: Date.now() };
      const next = [entry, ...current.filter((conversation) => conversation.id !== id)];
      writeConversations(next);
      return next;
    });
  }, []);

  const send = useCallback(
    async (question: string) => {
      if (loading) return;
      const id = sessionId;
      setBanner(null);
      setLoading(true);
      setMessages((current) => [...current, { id: nextId(), role: "user", content: question, sources: [] }]);
      rememberConversation(id, question);
      try {
        const response = await sendQuestion(id, question);
        if (activeSession.current !== id) return; // user switched conversation while waiting
        setMessages((current) => [
          ...current,
          {
            id: nextId(),
            role: "assistant",
            content: response.answer,
            sources: response.sources,
            meta: { outcome: response.outcome, model: response.model, cached: response.cached, timings: response.timings },
          },
        ]);
      } catch (error) {
        if (activeSession.current !== id) return;
        const message =
          error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
        setMessages((current) => [
          ...current,
          { id: nextId(), role: "assistant", content: message, sources: [], error: true },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [loading, sessionId, rememberConversation],
  );

  const startNew = () => {
    setSessionId(newSessionId());
    setMessages([]);
    setBanner(null);
    setSidebarOpen(false);
  };

  const clearChat = async () => {
    const id = sessionId;
    try {
      await clearSession(id);
    } catch {
      setBanner("Couldn't clear the conversation on the server. Please try again.");
      return;
    }
    setConversations((current) => {
      const next = current.filter((conversation) => conversation.id !== id);
      writeConversations(next);
      return next;
    });
    startNew();
  };

  const empty = messages.length === 0 && !restoring;

  return (
    <div className="flex h-full">
      <Sidebar
        conversations={conversations}
        activeId={sessionId}
        status={status}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onNew={startNew}
        onSelect={(id) => {
          setSessionId(id);
          setBanner(null);
          setSidebarOpen(false);
        }}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 flex-none items-center justify-between border-b border-line bg-paper px-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open menu"
              className="rounded-md p-1.5 hover:bg-stone-100 md:hidden"
            >
              <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
                <path d="M3 6h14M3 10h14M3 14h14" strokeLinecap="round" />
              </svg>
            </button>
            <span className="text-sm font-medium">Assistant</span>
            <span className="hidden text-xs text-stone-400 sm:inline">Grounded in DarGlobal and Wasalt.sa public data</span>
          </div>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={clearChat}
              disabled={loading}
              className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-stone-600 transition-colors hover:border-ink hover:text-ink disabled:opacity-40"
            >
              Clear chat
            </button>
          )}
        </header>

        {banner && (
          <div role="alert" className="flex items-center justify-between gap-3 border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
            <span>{banner}</span>
            <button type="button" onClick={() => setBanner(null)} aria-label="Dismiss" className="text-lg leading-none">
              ×
            </button>
          </div>
        )}

        <div className="scroll-slim flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-4 py-8">
            {empty ? (
              <div className="animate-rise pt-[6vh]">
                <h1 className="font-display text-4xl leading-tight sm:text-5xl">
                  Ask about developments,
                  <br />
                  locations and listings.
                </h1>
                <p className="mt-4 max-w-xl text-[15px] leading-7 text-stone-600">
                  PropIntel answers from information collected from DarGlobal and Wasalt.sa, tells you which site each
                  fact came from, and links every source. If something isn't in the data, it says so.
                </p>
                <div className="mt-8 grid gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => send(suggestion)}
                      className="rounded-xl border border-line bg-white px-4 py-3 text-left text-sm leading-5 text-stone-700 transition-colors hover:border-ink hover:text-ink"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-8">
                {restoring && <p className="text-sm text-stone-400">Loading conversation…</p>}
                {messages.map((message) => (
                  <Message key={message.id} message={message} />
                ))}
                {loading && <TypingIndicator />}
              </div>
            )}
            <div ref={bottom} className="h-4" />
          </div>
        </div>

        <Composer disabled={loading || restoring} onSend={send} />
      </main>
    </div>
  );
}

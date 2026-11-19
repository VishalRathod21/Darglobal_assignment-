import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, clearSession, getIngestionStatus, loadHistory, sendQuestion } from "./api";
import { Composer } from "./components/Composer";
import { Message, TypingIndicator } from "./components/Message";
import { Sidebar } from "./components/Sidebar";
import { newSessionId, readConversations, writeConversations } from "./storage";
import type { ChatMessage, Conversation, IngestionStatus } from "./types";

interface SuggestionCard {
  category: "DarGlobal" | "Wasalt" | "Corporate";
  icon: string;
  query: string;
  desc: string;
}

const FEATURED_SUGGESTIONS: SuggestionCard[] = [
  {
    category: "DarGlobal",
    icon: "🏰",
    query: "Which projects does DarGlobal have in Oman?",
    desc: "Aida, coastal masterplans & development highlights",
  },
  {
    category: "DarGlobal",
    icon: "👑",
    query: "What amenities does Trump Tower Jeddah offer?",
    desc: "Luxury specifications, views & branded features",
  },
  {
    category: "Corporate",
    icon: "📰",
    query: "What did DarGlobal announce about Jeddah in November 2026?",
    desc: "Latest press releases, partnerships & milestones",
  },
  {
    category: "Wasalt",
    icon: "📍",
    query: "Show me 3-bedroom apartments for sale in Riyadh under SAR 800,000",
    desc: "Marketplace listings, verified prices & districts",
  },
  {
    category: "DarGlobal",
    icon: "🌆",
    query: "What is DG1 and where is it located?",
    desc: "Downtown Dubai canal-front architectural tower",
  },
  {
    category: "Corporate",
    icon: "💼",
    query: "Why invest with DarGlobal?",
    desc: "Global portfolio reach, co-branding & investor value",
  },
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

  const deleteConversation = (id: string) => {
    setConversations((current) => {
      const next = current.filter((c) => c.id !== id);
      writeConversations(next);
      return next;
    });
    if (id === sessionId) {
      startNew();
    }
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
    <div className="flex h-full bg-slate-50 font-sans text-slate-900">
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
        onDeleteConversation={deleteConversation}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {/* Top Executive Navigation Bar */}
        <header className="flex h-16 flex-none items-center justify-between border-b border-slate-200/80 bg-white/90 px-4 sm:px-6 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open menu"
              className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 md:hidden"
            >
              <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 6h14M3 10h14M3 14h14" strokeLinecap="round" />
              </svg>
            </button>
            <div className="flex items-center gap-2">
              <span className="font-display text-sm font-bold tracking-tight text-slate-900">
                AI Advisory Assistant
              </span>
              <span className="hidden sm:inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-medium text-slate-600">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                DarGlobal & Wasalt.sa
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {status?.chunks && (
              <span className="hidden lg:inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-800 border border-amber-200/60">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-600" />
                {status.chunks} Chunks Indexed
              </span>
            )}
            {messages.length > 0 && (
              <button
                type="button"
                onClick={clearChat}
                disabled={loading}
                className="flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-xs transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:opacity-40"
              >
                <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 6h12M10 6v10M7 6v10m6-10v10" strokeLinecap="round" />
                </svg>
                <span>Clear</span>
              </button>
            )}
          </div>
        </header>

        {banner && (
          <div role="alert" className="flex items-center justify-between gap-3 border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
            <span>{banner}</span>
            <button type="button" onClick={() => setBanner(null)} aria-label="Dismiss" className="text-lg leading-none font-bold">
              ×
            </button>
          </div>
        )}

        {/* Chat / Hero Scroll Area */}
        <div className="scroll-slim flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
            {empty ? (
              <div className="animate-rise pt-[3vh] sm:pt-[5vh]">
                {/* Hero Badge */}
                <div className="inline-flex items-center gap-2 rounded-full border border-amber-300/60 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-900 shadow-xs">
                  <span className="flex h-2 w-2 rounded-full bg-amber-600 animate-pulse" />
                  Grounded Real Estate RAG
                </div>

                {/* Hero Title */}
                <h1 className="mt-4 font-display text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl sm:leading-[1.15]">
                  Luxury Developments &
                  <br />
                  <span className="bg-gradient-to-r from-amber-600 via-amber-700 to-amber-900 bg-clip-text text-transparent">
                    Saudi Property Intelligence.
                  </span>
                </h1>

                {/* Hero Subtitle */}
                <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-slate-600">
                  Synthesizes official public data from <span className="font-semibold text-slate-800">DarGlobal</span> international luxury projects and <span className="font-semibold text-slate-800">Wasalt.sa</span> Saudi real estate listings. Every claim is strictly grounded with transparent citations.
                </p>

                {/* Value Props Pills */}
                <div className="mt-5 flex flex-wrap gap-2 text-xs font-medium text-slate-500">
                  <span className="inline-flex items-center gap-1.5 rounded-lg bg-white border border-slate-200/80 px-2.5 py-1">
                    ✓ Hybrid Vector + BM25 RRF
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-lg bg-white border border-slate-200/80 px-2.5 py-1">
                    ✓ Zero Hallucination Guardrail
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-lg bg-white border border-slate-200/80 px-2.5 py-1">
                    ✓ OpenRouter Free Model Tier
                  </span>
                </div>

                {/* Curated Prompt Cards */}
                <div className="mt-8">
                  <div className="mb-3 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    Suggested Inquiries
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {FEATURED_SUGGESTIONS.map((s) => (
                      <button
                        key={s.query}
                        type="button"
                        onClick={() => send(s.query)}
                        className="group flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 text-left shadow-xs transition-all duration-200 hover:-translate-y-0.5 hover:border-amber-500/70 hover:shadow-md active:scale-[0.99]"
                      >
                        <div>
                          <div className="flex items-center justify-between text-xs text-slate-400">
                            <span className="text-base">{s.icon}</span>
                            <span
                              className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${
                                s.category === "DarGlobal"
                                  ? "bg-amber-50 text-amber-800"
                                  : s.category === "Wasalt"
                                  ? "bg-emerald-50 text-emerald-800"
                                  : "bg-slate-100 text-slate-700"
                              }`}
                            >
                              {s.category}
                            </span>
                          </div>
                          <div className="mt-2 text-sm font-bold text-slate-900 group-hover:text-amber-800 transition-colors">
                            {s.query}
                          </div>
                        </div>
                        <div className="mt-2 text-[12px] text-slate-500 line-clamp-1">
                          {s.desc}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-6 sm:space-y-8">
                {restoring && (
                  <div className="flex items-center gap-2 rounded-xl bg-slate-100 p-3 text-xs text-slate-500">
                    <span className="h-2 w-2 rounded-full bg-slate-400 animate-pulse" />
                    <span>Restoring session history from server...</span>
                  </div>
                )}
                {messages.map((message) => (
                  <Message key={message.id} message={message} />
                ))}
                {loading && <TypingIndicator />}
              </div>
            )}
            <div ref={bottom} className="h-6" />
          </div>
        </div>

        {/* Input Dock */}
        <Composer disabled={loading || restoring} onSend={send} />
      </main>
    </div>
  );
}

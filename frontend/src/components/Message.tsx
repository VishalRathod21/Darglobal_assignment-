import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage, SourceRef } from "../types";

const OUTCOME_NOTE: Record<string, { label: string; style: string }> = {
  unknown: {
    label: "Not found in knowledge base",
    style: "bg-amber-50 text-amber-800 border-amber-200/70",
  },
  blocked: {
    label: "Request declined",
    style: "bg-rose-50 text-rose-800 border-rose-200/70",
  },
  degraded: {
    label: "LLM unavailable: showing retrieved passages",
    style: "bg-blue-50 text-blue-800 border-blue-200/70",
  },
};

/** Turn "[2]" into a markdown link so it can be rendered as a clickable citation chip. */
function linkCitations(text: string, valid: Set<number>): string {
  return text.replace(/\[(\d{1,2})\]/g, (match, digits) =>
    valid.has(Number(digits)) ? `[${digits}](#cite-${digits})` : match,
  );
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function SourceCard({ source, highlighted }: { source: SourceRef; highlighted: boolean }) {
  const isDarGlobal = source.source === "darglobal";
  const hostname = new URL(source.url).hostname.replace(/^www\./, "");

  return (
    <a
      id={`cite-${source.number}`}
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className={`group relative flex flex-col justify-between rounded-xl border bg-white p-3.5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md ${
        highlighted
          ? "border-amber-500 ring-2 ring-amber-500/30 shadow-md bg-amber-50/20"
          : "border-slate-200/85 hover:border-slate-400"
      }`}
    >
      <div>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span
              className={`flex h-5 w-5 flex-none items-center justify-center rounded-full text-[10px] font-bold ${
                isDarGlobal
                  ? "bg-amber-600 text-white shadow-xs"
                  : "bg-emerald-600 text-white shadow-xs"
              }`}
            >
              {source.number}
            </span>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                isDarGlobal
                  ? "bg-amber-50 text-amber-800 border border-amber-200/60"
                  : "bg-emerald-50 text-emerald-800 border border-emerald-200/60"
              }`}
            >
              {source.source_label}
            </span>
            <span className="text-[11px] text-slate-400">·</span>
            <span className="text-[11px] font-medium capitalize text-slate-500">
              {source.doc_type}
            </span>
          </div>
          <svg
            viewBox="0 0 20 20"
            className="h-3.5 w-3.5 text-slate-400 transition-colors group-hover:text-slate-700"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden
          >
            <path
              d="M7 13l6-6M8 7h5v5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        <div className="mt-2 line-clamp-1 text-sm font-semibold text-slate-900 group-hover:text-amber-800 transition-colors">
          {source.title}
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">
          {source.snippet}
        </p>
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2 text-[11px] text-slate-400">
        <span className="font-mono text-[10px] font-medium text-slate-500 truncate max-w-[140px]">
          {hostname}
        </span>
        <span className="flex-none text-[10px]">
          Collected {formatDate(source.collected_at)}
        </span>
      </div>
    </a>
  );
}

export function Message({ message }: { message: ChatMessage }) {
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  const copyText = () => {
    if (!message.content) return;
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (message.role === "user") {
    return (
      <div className="flex animate-rise justify-end">
        <div className="relative max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-gradient-to-br from-slate-900 via-slate-800 to-slate-950 px-5 py-3 text-[15px] font-medium leading-relaxed text-white shadow-md shadow-slate-900/10">
          {message.content}
        </div>
      </div>
    );
  }

  const valid = new Set(message.sources.map((source) => source.number));
  const noteInfo = message.meta ? OUTCOME_NOTE[message.meta.outcome] : undefined;

  return (
    <div className="animate-rise group/msg">
      {/* Assistant Header & Actions */}
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-amber-600 via-amber-700 to-slate-900 text-[11px] font-bold text-white shadow-sm ring-1 ring-amber-500/20">
            PI
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-slate-900 tracking-tight">
              PropIntel
            </span>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" title="Online" />
          </div>
          {noteInfo && (
            <span
              className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${noteInfo.style}`}
            >
              {noteInfo.label}
            </span>
          )}
        </div>

        {/* Copy Button */}
        {message.content && !message.error && (
          <button
            type="button"
            onClick={copyText}
            className="flex items-center gap-1 rounded-lg border border-slate-200/80 bg-white px-2 py-1 text-[11px] font-medium text-slate-500 opacity-80 transition-all hover:bg-slate-50 hover:text-slate-800 hover:border-slate-300"
            title="Copy answer to clipboard"
          >
            {copied ? (
              <>
                <svg
                  viewBox="0 0 20 20"
                  className="h-3.5 w-3.5 text-emerald-600"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <path d="M5 10l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="text-emerald-700 font-semibold">Copied!</span>
              </>
            ) : (
              <>
                <svg
                  viewBox="0 0 20 20"
                  className="h-3.5 w-3.5 text-slate-400"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                >
                  <rect x="6" y="6" width="10" height="10" rx="2" />
                  <path d="M4 14V4a2 2 0 012-2h10" />
                </svg>
                <span>Copy</span>
              </>
            )}
          </button>
        )}
      </div>

      {/* Answer Body */}
      <div
        className={`rounded-2xl border border-slate-200/70 bg-white/90 p-5 shadow-xs backdrop-blur-xs transition-shadow hover:shadow-sm ${
          message.error ? "border-red-200 bg-red-50/60 text-red-800" : ""
        }`}
      >
        <div className="prose-answer">
          <ReactMarkdown
            components={{
              a: ({ href, children }) => {
                const cite = href?.match(/^#cite-(\d+)$/);
                if (cite) {
                  const number = Number(cite[1]);
                  const src = message.sources.find((s) => s.number === number);
                  const isDar = src?.source === "darglobal";

                  return (
                    <button
                      type="button"
                      onClick={() => {
                        setHighlighted(number);
                        const el = document.getElementById(`cite-${number}`);
                        el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                      }}
                      title={src ? `${src.source_label}: ${src.title}` : `Source [${number}]`}
                      className={`mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 cursor-pointer items-center justify-center rounded-md border px-1 align-middle text-[10px] font-bold transition-all ${
                        highlighted === number
                          ? "bg-amber-600 text-white border-amber-600 ring-2 ring-amber-300"
                          : isDar
                          ? "border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-600 hover:text-white hover:border-amber-600"
                          : "border-emerald-300 bg-emerald-50 text-emerald-900 hover:bg-emerald-600 hover:text-white hover:border-emerald-600"
                      }`}
                    >
                      {number}
                    </button>
                  );
                }
                return (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-amber-800 underline underline-offset-3 hover:text-amber-900"
                  >
                    {children}
                  </a>
                );
              },
            }}
          >
            {linkCitations(message.content, valid)}
          </ReactMarkdown>
        </div>

        {/* Source Cards Grid */}
        {message.sources.length > 0 && (
          <div className="mt-5 border-t border-slate-100 pt-4">
            <div className="mb-2.5 flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                <svg
                  viewBox="0 0 20 20"
                  className="h-3.5 w-3.5 text-slate-400"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M4 4h12a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1z" />
                  <path d="M8 4v12" />
                </svg>
                <span>Verified Sources ({message.sources.length})</span>
              </div>
              <span className="text-[10px] text-slate-400">Click citation badge or card to verify</span>
            </div>
            <div className="grid gap-2.5 sm:grid-cols-2">
              {message.sources.map((source) => (
                <SourceCard
                  key={source.number}
                  source={source}
                  highlighted={highlighted === source.number}
                />
              ))}
            </div>
          </div>
        )}

        {/* Answer Metadata Footer */}
        {message.meta &&
          message.meta.outcome !== "greeting" &&
          message.meta.outcome !== "blocked" && (
            <div className="mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2.5 text-[11px] text-slate-400">
              {message.meta.model && (
                <span className="flex items-center gap-1 font-mono text-[10px] text-slate-500">
                  <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                  {message.meta.model}
                </span>
              )}
              <span className="font-mono text-[10px]">
                {(message.meta.timings.total_ms / 1000).toFixed(2)}s latency
              </span>
              {message.meta.cached && (
                <span className="rounded bg-emerald-50 px-1.5 py-0.2 text-[10px] font-semibold text-emerald-700 border border-emerald-200/50">
                  Cached
                </span>
              )}
            </div>
          )}
      </div>
    </div>
  );
}

export function TypingIndicator() {
  return (
    <div
      className="flex items-center gap-3 rounded-2xl border border-slate-200/70 bg-white/80 p-4 shadow-xs backdrop-blur-xs"
      role="status"
      aria-live="polite"
    >
      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-amber-600 via-amber-700 to-slate-900 text-[11px] font-bold text-white shadow-sm ring-1 ring-amber-500/20">
        PI
      </div>
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-slate-700">
          Synthesizing from DarGlobal & Wasalt corpus
        </span>
        <span className="flex gap-1" aria-hidden>
          {[0, 1, 2].map((dot) => (
            <span
              key={dot}
              className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-amber-600"
              style={{ animationDelay: `${dot * 0.2}s` }}
            />
          ))}
        </span>
      </div>
    </div>
  );
}

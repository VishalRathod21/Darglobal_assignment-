import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage, SourceRef } from "../types";

const OUTCOME_NOTE: Record<string, string> = {
  unknown: "Not found in the knowledge base",
  blocked: "Request declined",
  degraded: "Language model unavailable: showing retrieved passages",
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
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className={`group block rounded-xl border bg-white p-3 transition-colors hover:border-ink ${
        highlighted ? "border-ink ring-1 ring-ink" : "border-line"
      }`}
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-stone-500">
        <span className="flex h-5 w-5 flex-none items-center justify-center rounded-full bg-ink text-[10px] font-semibold text-white">
          {source.number}
        </span>
        <span className="font-semibold text-ink">{source.source_label}</span>
        <span aria-hidden>·</span>
        <span>{source.doc_type}</span>
      </div>
      <div className="mt-1.5 line-clamp-1 text-sm font-medium group-hover:underline">{source.title}</div>
      <p className="mt-1 line-clamp-2 text-xs leading-5 text-stone-600">{source.snippet}</p>
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-stone-400">
        <span className="truncate">{new URL(source.url).hostname.replace(/^www\./, "")}</span>
        <span className="flex-none">Collected {formatDate(source.collected_at)}</span>
      </div>
    </a>
  );
}

export function Message({ message }: { message: ChatMessage }) {
  const [highlighted, setHighlighted] = useState<number | null>(null);

  if (message.role === "user") {
    return (
      <div className="flex animate-rise justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-[15px] leading-6 text-white">
          {message.content}
        </div>
      </div>
    );
  }

  const valid = new Set(message.sources.map((source) => source.number));
  const note = message.meta ? OUTCOME_NOTE[message.meta.outcome] : undefined;

  return (
    <div className="animate-rise">
      <div className="mb-2 flex items-center gap-2 text-xs text-stone-500">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-ink text-[10px] font-bold text-white">
          PI
        </span>
        <span className="font-medium text-ink">PropIntel</span>
        {note && <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-stone-600">{note}</span>}
      </div>

      <div className={`prose-answer ${message.error ? "text-red-700" : ""}`}>
        <ReactMarkdown
          components={{
            a: ({ href, children }) => {
              const cite = href?.match(/^#cite-(\d+)$/);
              if (cite) {
                const number = Number(cite[1]);
                return (
                  <button
                    type="button"
                    onClick={() => setHighlighted(number)}
                    title={message.sources.find((source) => source.number === number)?.title}
                    className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-0.5 items-center justify-center rounded-full bg-stone-200 px-1 align-middle text-[10px] font-semibold text-ink transition-colors hover:bg-ink hover:text-white"
                  >
                    {number}
                  </button>
                );
              }
              return (
                <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                  {children}
                </a>
              );
            },
          }}
        >
          {linkCitations(message.content, valid)}
        </ReactMarkdown>
      </div>

      {message.sources.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-stone-500">
            Sources ({message.sources.length})
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {message.sources.map((source) => (
              <SourceCard key={source.number} source={source} highlighted={highlighted === source.number} />
            ))}
          </div>
        </div>
      )}

      {message.meta && message.meta.outcome !== "greeting" && message.meta.outcome !== "blocked" && (
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-stone-400">
          {message.meta.model && <span>{message.meta.model}</span>}
          <span>{(message.meta.timings.total_ms / 1000).toFixed(1)}s</span>
          {message.meta.cached && <span>served from cache</span>}
        </div>
      )}
    </div>
  );
}

export function TypingIndicator() {
  return (
    <div className="flex items-center gap-2 text-sm text-stone-500" role="status" aria-live="polite">
      <span className="flex h-6 w-6 items-center justify-center rounded-md bg-ink text-[10px] font-bold text-white">
        PI
      </span>
      <span>Searching sources</span>
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((dot) => (
          <span
            key={dot}
            className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-stone-500"
            style={{ animationDelay: `${dot * 0.2}s` }}
          />
        ))}
      </span>
    </div>
  );
}

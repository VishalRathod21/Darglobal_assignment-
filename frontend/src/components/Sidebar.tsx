import type { Conversation, IngestionStatus } from "../types";

const SOURCE_NAMES: Record<string, string> = { darglobal: "DarGlobal", wasalt: "Wasalt.sa" };

function describe(docTypes: Record<string, number>): string {
  const labels: Record<string, string> = { project: "projects", article: "press releases", page: "pages", listing: "listings" };
  return Object.entries(docTypes)
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => `${count} ${labels[type] ?? type}`)
    .join(" · ");
}

function formatDate(iso?: string): string {
  if (!iso) return "unknown";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

interface Props {
  conversations: Conversation[];
  activeId: string;
  status: IngestionStatus | null;
  open: boolean;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
}

export function Sidebar({ conversations, activeId, status, open, onClose, onNew, onSelect }: Props) {
  return (
    <>
      {open && <div className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={onClose} aria-hidden />}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-line bg-white transition-transform md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-xs font-bold text-white">PI</span>
          <div>
            <div className="font-display text-lg leading-5">PropIntel AI</div>
            <div className="text-[11px] text-stone-500">Real estate intelligence</div>
          </div>
        </div>

        <div className="px-4">
          <button
            type="button"
            onClick={onNew}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-ink px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-85"
          >
            <span aria-hidden className="text-base leading-none">+</span> New conversation
          </button>
        </div>

        <nav className="scroll-slim mt-5 flex-1 overflow-y-auto px-2" aria-label="Conversation history">
          <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-stone-400">History</div>
          {conversations.length === 0 && (
            <p className="px-3 py-2 text-xs leading-5 text-stone-400">Your conversations will appear here.</p>
          )}
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              type="button"
              onClick={() => onSelect(conversation.id)}
              className={`mb-0.5 block w-full truncate rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                conversation.id === activeId ? "bg-stone-100 font-medium" : "text-stone-600 hover:bg-stone-50"
              }`}
            >
              {conversation.title}
            </button>
          ))}
        </nav>

        <div className="border-t border-line px-5 py-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-stone-400">Knowledge base</div>
          {status?.sources ? (
            <ul className="space-y-2.5">
              {Object.entries(status.sources).map(([key, stats]) => (
                <li key={key} className="text-xs leading-5">
                  <div className="flex items-baseline justify-between">
                    <span className="font-medium">{SOURCE_NAMES[key] ?? key}</span>
                    <span className="text-stone-400">{formatDate(stats.last_scraped_at)}</span>
                  </div>
                  <div className="text-stone-500">{describe(stats.doc_types)}</div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-stone-400">Loading…</p>
          )}
          <p className="mt-3 text-[11px] leading-4 text-stone-400">
            Answers use only this collected data. Prices and availability change, so confirm on the official sites.
          </p>
        </div>
      </aside>
    </>
  );
}

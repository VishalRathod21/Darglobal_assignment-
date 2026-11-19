import type { Conversation, IngestionStatus } from "../types";

const SOURCE_NAMES: Record<string, string> = {
  darglobal: "DarGlobal",
  wasalt: "Wasalt.sa",
};

function describe(docTypes: Record<string, number>): string {
  const labels: Record<string, string> = {
    project: "projects",
    article: "press releases",
    page: "corporate pages",
    listing: "listings",
  };
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
  onDeleteConversation?: (id: string) => void;
}

export function Sidebar({
  conversations,
  activeId,
  status,
  open,
  onClose,
  onNew,
  onSelect,
  onDeleteConversation,
}: Props) {
  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-30 bg-slate-900/40 backdrop-blur-sm transition-opacity md:hidden"
          onClick={onClose}
          aria-hidden
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200/90 bg-white shadow-xl md:shadow-none transition-transform duration-200 ease-out md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Brand Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-amber-600 via-amber-700 to-slate-900 text-xs font-bold tracking-wider text-white shadow-md shadow-amber-600/20">
              PI
            </div>
            <div>
              <div className="font-display text-base font-bold tracking-tight text-slate-900 flex items-center gap-1.5">
                PropIntel AI
                <span className="inline-block rounded bg-amber-100 px-1.5 py-0.2 text-[9px] font-bold uppercase tracking-wider text-amber-800">
                  Pro
                </span>
              </div>
              <div className="text-[11px] font-medium text-slate-400">Real Estate Intelligence</div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 md:hidden"
            aria-label="Close sidebar"
          >
            <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* New Chat Button */}
        <div className="px-4 pt-2 pb-1">
          <button
            type="button"
            onClick={onNew}
            className="group flex w-full items-center justify-center gap-2 rounded-xl bg-slate-900 px-3.5 py-2.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-slate-800 hover:shadow active:scale-[0.99]"
          >
            <svg
              viewBox="0 0 20 20"
              className="h-4 w-4 transition-transform group-hover:rotate-90"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
            >
              <path d="M10 4v12M4 10h12" strokeLinecap="round" />
            </svg>
            <span>New conversation</span>
          </button>
        </div>

        {/* Conversation History */}
        <nav className="scroll-slim mt-3 flex-1 overflow-y-auto px-3" aria-label="Conversation history">
          <div className="flex items-center justify-between px-2 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <span>Conversations</span>
            <span className="text-[10px] font-semibold text-slate-400">{conversations.length}</span>
          </div>

          {conversations.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 p-4 text-center">
              <p className="text-xs text-slate-400 leading-relaxed">
                No conversations yet. Ask a question to begin.
              </p>
            </div>
          ) : (
            <div className="space-y-1 pt-1">
              {conversations.map((conversation) => {
                const isActive = conversation.id === activeId;
                return (
                  <div
                    key={conversation.id}
                    className={`group relative flex items-center rounded-xl transition-all ${
                      isActive
                        ? "bg-slate-100 text-slate-950 font-medium shadow-xs"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelect(conversation.id)}
                      className="flex flex-1 items-center gap-2.5 overflow-hidden px-3 py-2.5 text-left text-xs"
                    >
                      <svg
                        viewBox="0 0 20 20"
                        className={`h-3.5 w-3.5 flex-none transition-colors ${
                          isActive ? "text-amber-600" : "text-slate-400 group-hover:text-slate-600"
                        }`}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.8"
                      >
                        <path
                          d="M4 5a2 2 0 012-2h8a2 2 0 012 2v7a2 2 0 01-2 2H8l-4 4V5z"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                      <span className="truncate">{conversation.title || "Untitled Chat"}</span>
                    </button>
                    {onDeleteConversation && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteConversation(conversation.id);
                        }}
                        className="mr-2 hidden rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-red-600 group-hover:block"
                        title="Delete conversation"
                        aria-label="Delete conversation"
                      >
                        <svg viewBox="0 0 20 20" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M4 6h12M8 6V4h4v2m-6 4v6m4-6v6m3-6v8a1 1 0 01-1 1H6a1 1 0 01-1-1v-8" strokeLinecap="round" />
                        </svg>
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </nav>

        {/* Knowledge Base Card */}
        <div className="border-t border-slate-100 bg-slate-50/70 p-4">
          <div className="flex items-center justify-between pb-2">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Knowledge Base
            </span>
            <span className="flex items-center gap-1.5 text-[10px] font-semibold text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live Index
            </span>
          </div>

          {status?.sources ? (
            <div className="space-y-2 rounded-xl bg-white p-3 border border-slate-200/80 shadow-xs">
              {Object.entries(status.sources).map(([key, stats]) => {
                const isDar = key === "darglobal";
                return (
                  <div key={key} className="text-xs">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 font-semibold text-slate-900">
                        <span
                          className={`h-2 w-2 rounded-full ${isDar ? "bg-amber-600" : "bg-emerald-600"}`}
                        />
                        {SOURCE_NAMES[key] ?? key}
                      </span>
                      <span className="text-[10px] text-slate-400 font-mono">
                        {stats.records} docs
                      </span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-slate-500 truncate">
                      {describe(stats.doc_types)}
                    </div>
                  </div>
                );
              })}
              <div className="pt-1.5 border-t border-slate-100 flex items-center justify-between text-[10px] text-slate-500">
                <span>Total Chunks</span>
                <span className="font-semibold text-slate-800">{status.chunks ?? 716}</span>
              </div>
            </div>
          ) : (
            <div className="p-3 text-xs text-slate-400">Loading index status…</div>
          )}

          <div className="mt-2.5 flex items-center gap-1 text-[10px] leading-tight text-slate-400">
            <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 flex-none text-slate-400" fill="none" stroke="currentColor">
              <circle cx="10" cy="10" r="8" strokeWidth="1.6" />
              <path d="M10 9v5m0-8h.01" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <span>Answers cite verified public data only.</span>
          </div>
        </div>
      </aside>
    </>
  );
}

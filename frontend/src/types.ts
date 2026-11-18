export type Outcome = "answered" | "unknown" | "greeting" | "blocked" | "degraded";

export interface SourceRef {
  number: number;
  source: "darglobal" | "wasalt";
  source_label: string;
  doc_type: string;
  title: string;
  url: string;
  snippet: string;
  collected_at: string;
  score: number;
}

export interface ChatResponse {
  session_id: string;
  answer: string;
  outcome: Outcome;
  sources: SourceRef[];
  model: string | null;
  cached: boolean;
  usage: { prompt_tokens: number; completion_tokens: number };
  timings: { total_ms: number; retrieval_ms: number; llm_ms: number };
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: SourceRef[];
  // Present only for answers received in this browser session.
  meta?: Pick<ChatResponse, "outcome" | "model" | "cached" | "timings">;
  error?: boolean;
}

export interface SourceStats {
  records: number;
  chunks: number;
  doc_types: Record<string, number>;
  last_scraped_at: string;
}

export interface IngestionStatus {
  indexed_at?: string;
  records?: number;
  chunks?: number;
  sources?: Record<string, SourceStats>;
}

export interface Conversation {
  id: string;
  title: string;
  updatedAt: number;
}

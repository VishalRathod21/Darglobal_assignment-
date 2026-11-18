import type { ChatMessage, ChatResponse, IngestionStatus, SourceRef } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  if (!response.ok) {
    let detail = "Something went wrong. Please try again.";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body: keep the generic message */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export function sendQuestion(sessionId: string, question: string, signal?: AbortSignal): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, question }),
    signal,
  });
}

interface StoredMessage {
  role: "user" | "assistant";
  content: string;
  sources: SourceRef[];
  created_at: number;
}

export async function loadHistory(sessionId: string): Promise<ChatMessage[]> {
  const data = await request<{ messages: StoredMessage[] }>(`/sessions/${sessionId}/messages`);
  return data.messages.map((message, index) => ({
    id: `${sessionId}-${index}`,
    role: message.role,
    content: message.content,
    sources: message.sources ?? [],
  }));
}

export function clearSession(sessionId: string): Promise<unknown> {
  return request(`/sessions/${sessionId}`, { method: "DELETE" });
}

export function getIngestionStatus(): Promise<IngestionStatus> {
  return request<IngestionStatus>("/knowledge-base");
}

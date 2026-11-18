import type { Conversation } from "./types";

// Only conversation ids and titles live in the browser. The messages themselves are
// stored server-side and fetched by id, so a reload restores the full thread.
const KEY = "propintel.conversations";
const MAX_CONVERSATIONS = 20;

export function newSessionId(): string {
  const random = crypto.getRandomValues(new Uint8Array(12));
  return "s_" + Array.from(random, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function readConversations(): Conversation[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function writeConversations(conversations: Conversation[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(conversations.slice(0, MAX_CONVERSATIONS)));
  } catch {
    /* private mode or full storage: history simply won't persist */
  }
}

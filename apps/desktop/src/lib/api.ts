import type { ChatMessage, ChatResponse, Signal, StandupBrief } from "./types";

const BASE_URL: string =
  (import.meta.env.VITE_IRMA_API as string | undefined) ??
  "http://127.0.0.1:8765";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText} — ${detail}`);
  }
  return (await res.json()) as T;
}

export async function fetchStandup(): Promise<StandupBrief> {
  const res = await fetch(`${BASE_URL}/api/v1/standup`);
  return jsonOrThrow<StandupBrief>(res);
}

export async function fetchSignals(): Promise<Signal[]> {
  const res = await fetch(`${BASE_URL}/api/v1/signals`);
  return jsonOrThrow<Signal[]>(res);
}

export async function forceRefresh(): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/v1/refresh`, { method: "POST" });
  if (!res.ok) throw new Error(`refresh failed: HTTP ${res.status}`);
}

export async function sendChat(messages: ChatMessage[]): Promise<ChatResponse> {
  const res = await fetch(`${BASE_URL}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  return jsonOrThrow<ChatResponse>(res);
}

export const IRMA_API_BASE = BASE_URL;

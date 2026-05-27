import type { AgentState } from "./types";
import { NOFARI_API_BASE } from "./api";

const KNOWN_STATES = new Set<AgentState>([
  "idle",
  "observing",
  "thinking",
  "alert",
]);

function isAgentState(value: string): value is AgentState {
  return (KNOWN_STATES as Set<string>).has(value);
}

export interface AgentStateSubscription {
  close: () => void;
}

/**
 * Subscribe to the backend AgentState SSE stream.
 *
 * EventSource handles reconnection itself; if the backend is not running yet
 * (Phase 1 dev), the connection silently fails and retries — leaving the
 * caller at whatever default state it started with.
 */
export function subscribeAgentState(
  onState: (s: AgentState) => void,
): AgentStateSubscription {
  const source = new EventSource(`${NOFARI_API_BASE}/api/v1/stream`);

  source.addEventListener("state", (ev: Event) => {
    const data = (ev as MessageEvent<string>).data;
    if (isAgentState(data)) onState(data);
  });

  // Swallow noisy error spam if the backend is offline; EventSource auto-retries.
  source.onerror = () => undefined;

  return {
    close: () => source.close(),
  };
}

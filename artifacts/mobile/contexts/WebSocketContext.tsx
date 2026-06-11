import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";
import { AppState } from "react-native";
import type { TickData, WSMessage } from "@/types/api";
import { getWsUrl } from "@/lib/api";

interface WebSocketState {
  connected: boolean;
  ticks: Record<string, TickData>;
  lastMessage: WSMessage | null;
  reconnectCount: number;
}

interface WebSocketContextValue extends WebSocketState {
  subscribe: (type: string, handler: (data: unknown) => void) => () => void;
}

const WebSocketContext = createContext<WebSocketContextValue>({
  connected: false,
  ticks: {},
  lastMessage: null,
  reconnectCount: 0,
  subscribe: () => () => {},
});

const BASE_RECONNECT_MS = 2000;
const MAX_RECONNECT_MS = 60000;

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<WebSocketState>({
    connected: false,
    ticks: {},
    lastMessage: null,
    reconnectCount: 0,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef<Map<string, Set<(data: unknown) => void>>>(new Map());
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const attemptRef = useRef(0);
  const appActiveRef = useRef(true);

  const subscribe = useCallback((type: string, handler: (data: unknown) => void) => {
    if (!handlersRef.current.has(type)) {
      handlersRef.current.set(type, new Set());
    }
    handlersRef.current.get(type)!.add(handler);
    return () => {
      handlersRef.current.get(type)?.delete(handler);
    };
  }, []);

  const scheduleReconnect = useCallback((connectFn: () => void) => {
    if (!mountedRef.current || !appActiveRef.current) return;
    // Exponential backoff with jitter: 2s, 4s, 8s ... capped at 60s
    const delay = Math.min(BASE_RECONNECT_MS * 2 ** attemptRef.current, MAX_RECONNECT_MS);
    const jitter = delay * 0.2 * Math.random();
    attemptRef.current += 1;
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = setTimeout(connectFn, delay + jitter);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    if (!appActiveRef.current) return;

    try {
      const ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        attemptRef.current = 0; // healthy again — reset backoff
        setState((s) => ({ ...s, connected: true }));
        ws.send(JSON.stringify({ type: "subscribe", channels: ["ticks", "trade_executions", "agent_status", "signals", "news"] }));
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const msg: WSMessage = JSON.parse(event.data);
          setState((s) => {
            const next = { ...s, lastMessage: msg };
            if (msg.type === "tick" && msg.data) {
              const tick = msg.data as TickData;
              next.ticks = { ...s.ticks, [tick.symbol]: tick };
            }
            return next;
          });

          const handlers = handlersRef.current.get(msg.type);
          if (handlers) {
            handlers.forEach((h) => h(msg.data));
          }
          const allHandlers = handlersRef.current.get("*");
          if (allHandlers) {
            allHandlers.forEach((h) => h(msg));
          }
        } catch (err) {
          console.warn("[WS] Failed to parse message:", err);
        }
      };

      ws.onclose = (event) => {
        if (!mountedRef.current) return;
        setState((s) => ({ ...s, connected: false, reconnectCount: s.reconnectCount + 1 }));
        if (appActiveRef.current) {
          console.warn(`[WS] Closed (code=${event.code}), reconnecting (attempt ${attemptRef.current + 1})`);
          scheduleReconnect(connect);
        }
      };

      ws.onerror = (err) => {
        console.warn("[WS] Connection error:", (err as { message?: string })?.message ?? "unknown");
        ws.close();
      };
    } catch (err) {
      console.warn("[WS] Failed to open socket:", err);
      scheduleReconnect(connect);
    }
  }, [scheduleReconnect]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 25000);

    // Pause the socket in background (battery/network); resume fresh on foreground
    const appStateSub = AppState.addEventListener("change", (next) => {
      const active = next === "active";
      appActiveRef.current = active;
      if (active) {
        attemptRef.current = 0;
        connect();
      } else {
        if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
        wsRef.current?.close();
      }
    });

    return () => {
      mountedRef.current = false;
      clearInterval(pingInterval);
      appStateSub.remove();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return (
    <WebSocketContext.Provider value={{ ...state, subscribe }}>
      {children}
    </WebSocketContext.Provider>
  );
}

export const useWebSocket = () => useContext(WebSocketContext);

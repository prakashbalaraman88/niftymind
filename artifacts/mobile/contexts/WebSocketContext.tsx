import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";
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

  const subscribe = useCallback((type: string, handler: (data: unknown) => void) => {
    if (!handlersRef.current.has(type)) {
      handlersRef.current.set(type, new Set());
    }
    handlersRef.current.get(type)!.add(handler);
    return () => {
      handlersRef.current.get(type)?.delete(handler);
    };
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
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
        } catch {}
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setState((s) => ({ ...s, connected: false, reconnectCount: s.reconnectCount + 1 }));
        reconnectTimerRef.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {}
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 25000);

    return () => {
      mountedRef.current = false;
      clearInterval(pingInterval);
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

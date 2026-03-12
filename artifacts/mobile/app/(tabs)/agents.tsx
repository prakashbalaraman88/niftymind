import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import colors from "@/constants/colors";
import { AGENT_INFO, AGENT_IDS } from "@/constants/agents";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { CardSkeleton } from "@/components/SkeletonLoader";
import type { Signal, AgentStatus } from "@/types/api";

export default function AgentsScreen() {
  const { subscribe } = useWebSocket();
  const queryClient = useQueryClient();

  const { data: agentData, isLoading: loadingAgents, isError: agentsError, refetch: refetchAgents, isRefetching } = useQuery({
    queryKey: ["agents"],
    queryFn: api.getAgents,
    refetchInterval: 30000,
    retry: false,
  });

  const { data: signalData, isLoading: loadingSignals, isError: signalsError, refetch: refetchSignals } = useQuery({
    queryKey: ["signals"],
    queryFn: () => api.getSignals(100),
    refetchInterval: 30000,
    retry: false,
  });

  const [liveSignals, setLiveSignals] = useState<Record<string, Signal>>({});
  const [liveActivity, setLiveActivity] = useState<Record<string, string>>({});

  useEffect(() => {
    const unsub1 = subscribe("signal", (data: any) => {
      if (data?.agent_id) {
        setLiveSignals((prev) => ({ ...prev, [data.agent_id]: data as Signal }));
      }
    });
    const unsub2 = subscribe("agent_status", (data: any) => {
      const id = data?.agent_id || data?.source;
      if (id) {
        setLiveActivity((prev) => ({ ...prev, [id]: new Date().toISOString() }));
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      }
    });
    return () => { unsub1(); unsub2(); };
  }, [subscribe, queryClient]);

  const agentStatusMap: Record<string, AgentStatus> = {};
  (agentData?.agents || []).forEach((a) => {
    agentStatusMap[a.source] = a;
  });

  const signalsByAgent: Record<string, Signal[]> = {};
  (signalData?.signals || []).forEach((s) => {
    if (!signalsByAgent[s.agent_id]) signalsByAgent[s.agent_id] = [];
    signalsByAgent[s.agent_id].push(s);
  });

  const handleRefresh = () => {
    refetchAgents();
    refetchSignals();
  };

  const isLoading = (loadingAgents || loadingSignals) && !agentsError && !signalsError;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      contentInsetAdjustmentBehavior="automatic"
      refreshControl={
        <RefreshControl refreshing={isRefetching} onRefresh={handleRefresh} tintColor={colors.light.tint} />
      }
    >
      {isLoading ? (
        Array.from({ length: 6 }).map((_, i) => <CardSkeleton key={i} />)
      ) : (
        AGENT_IDS.map((id) => {
          const info = AGENT_INFO[id];
          const status = agentStatusMap[id];
          const latest = liveSignals[id] || (signalsByAgent[id]?.[0]);
          const lastActive = liveActivity[id] || status?.timestamp || latest?.created_at;

          const isStale = lastActive
            ? Date.now() - new Date(lastActive).getTime() > 5 * 60 * 1000
            : true;

          const direction = latest?.direction;
          const dirVariant = direction === "BULLISH" ? "bullish" : direction === "BEARISH" ? "bearish" : "neutral";

          return (
            <Card key={id} style={isStale ? { ...styles.agentCard, ...styles.staleCard } : styles.agentCard}>
              <View style={styles.agentHeader}>
                <View style={styles.agentIconWrap}>
                  <Feather name={info.icon} size={18} color={colors.light.tint} />
                </View>
                <View style={styles.agentInfo}>
                  <Text style={styles.agentName}>{info.name}</Text>
                  <Text style={styles.agentId}>{id.replace("_", " #")}</Text>
                </View>
                <View style={styles.agentBadges}>
                  {direction ? (
                    <StatusBadge label={direction} variant={dirVariant} />
                  ) : (
                    <StatusBadge label="Idle" variant="inactive" />
                  )}
                  <View style={[styles.activeDot, { backgroundColor: isStale ? "#D1D5DB" : colors.light.green }]} />
                </View>
              </View>

              {latest && (
                <View style={styles.latestSignal}>
                  <View style={styles.signalRow}>
                    <Text style={styles.signalLabel}>Confidence</Text>
                    <View style={styles.confBarOuter}>
                      <View style={[styles.confBarInner, {
                        width: `${(latest.confidence ?? 0) * 100}%`,
                        backgroundColor: direction === "BULLISH" ? colors.light.green : direction === "BEARISH" ? colors.light.red : colors.light.textTertiary,
                      }]} />
                    </View>
                    <Text style={styles.confValue}>{((latest.confidence ?? 0) * 100).toFixed(0)}%</Text>
                  </View>
                  {!!latest.underlying && (
                    <View style={styles.signalRow}>
                      <Text style={styles.signalLabel}>Underlying</Text>
                      <Text style={styles.signalValue}>{latest.underlying}</Text>
                    </View>
                  )}
                  {!!latest.timeframe && (
                    <View style={styles.signalRow}>
                      <Text style={styles.signalLabel}>Timeframe</Text>
                      <Text style={styles.signalValue}>{latest.timeframe}</Text>
                    </View>
                  )}
                  {!!latest.reasoning && (
                    <Text style={styles.reasoning} numberOfLines={3}>
                      {latest.reasoning}
                    </Text>
                  )}
                </View>
              )}

              {lastActive && (
                <Text style={styles.lastActive}>
                  <Feather name="clock" size={10} color={colors.light.textTertiary} />{" "}
                  {formatTimeAgo(lastActive)}
                </Text>
              )}
            </Card>
          );
        })
      )}
    </ScrollView>
  );
}

function formatTimeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.light.background,
  },
  content: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 100,
  },
  agentCard: {
    marginBottom: 10,
  },
  staleCard: {
    opacity: 0.7,
  },
  agentHeader: {
    flexDirection: "row",
    alignItems: "center",
  },
  agentIconWrap: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: colors.light.tintLight,
    justifyContent: "center",
    alignItems: "center",
    marginRight: 10,
  },
  agentInfo: {
    flex: 1,
  },
  agentName: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  agentId: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: colors.light.textTertiary,
  },
  agentBadges: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  activeDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  latestSignal: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.light.border,
  },
  signalRow: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 6,
  },
  signalLabel: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
    width: 80,
  },
  signalValue: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.text,
    flex: 1,
  },
  confBarOuter: {
    flex: 1,
    height: 6,
    backgroundColor: colors.light.border,
    borderRadius: 3,
    marginHorizontal: 8,
    overflow: "hidden",
  },
  confBarInner: {
    height: 6,
    borderRadius: 3,
  },
  confValue: {
    fontSize: 12,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
    width: 36,
    textAlign: "right",
  },
  reasoning: {
    fontSize: 12,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
    lineHeight: 18,
    marginTop: 4,
  },
  lastActive: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: colors.light.textTertiary,
    marginTop: 8,
  },
});

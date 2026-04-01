import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  Animated,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import colors from "@/constants/colors";
import { AGENT_INFO, AGENT_IDS } from "@/constants/agents";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { CardSkeleton } from "@/components/SkeletonLoader";
import type { Signal, AgentStatus } from "@/types/api";

const C = colors.dark;

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
    const u1 = subscribe("signal", (data: any) => {
      if (data?.agent_id) setLiveSignals((prev) => ({ ...prev, [data.agent_id]: data as Signal }));
    });
    const u2 = subscribe("agent_status", (data: any) => {
      const id = data?.agent_id || data?.source;
      if (id) {
        setLiveActivity((prev) => ({ ...prev, [id]: new Date().toISOString() }));
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      }
    });
    return () => { u1(); u2(); };
  }, [subscribe, queryClient]);

  const agentStatusMap: Record<string, AgentStatus> = {};
  (agentData?.agents || []).forEach((a) => { agentStatusMap[a.source] = a; });

  const signalsByAgent: Record<string, Signal[]> = {};
  (signalData?.signals || []).forEach((s) => {
    if (!signalsByAgent[s.agent_id]) signalsByAgent[s.agent_id] = [];
    signalsByAgent[s.agent_id].push(s);
  });

  const handleRefresh = () => { refetchAgents(); refetchSignals(); };
  const isLoading = (loadingAgents || loadingSignals) && !agentsError && !signalsError;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={isRefetching} onRefresh={handleRefresh} tintColor={C.accentBright} />
      }
    >
      {isLoading ? (
        Array.from({ length: 6 }).map((_, i) => <CardSkeleton key={i} />)
      ) : (
        AGENT_IDS.map((id, index) => {
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
            <AgentCard
              key={id}
              agentId={id}
              info={info}
              latest={latest}
              lastActive={lastActive}
              isStale={isStale}
              dirVariant={dirVariant}
              direction={direction}
              index={index}
            />
          );
        })
      )}
    </ScrollView>
  );
}

function AgentCard({
  agentId, info, latest, lastActive, isStale, dirVariant, direction, index,
}: {
  agentId: string;
  info: any;
  latest?: Signal;
  lastActive?: string;
  isStale: boolean;
  dirVariant: "bullish" | "bearish" | "neutral";
  direction?: string;
  index: number;
}) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(20)).current;
  const dotScale = useRef(new Animated.Value(1)).current;
  const confBarWidth = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(opacity, { toValue: 1, duration: 400, delay: index * 55, useNativeDriver: true }),
      Animated.spring(translateY, { toValue: 0, delay: index * 55, useNativeDriver: true, damping: 16 }),
    ]).start();
  }, []);

  useEffect(() => {
    const confidence = latest?.confidence ?? 0;
    Animated.timing(confBarWidth, {
      toValue: confidence,
      duration: 800,
      useNativeDriver: false,
    }).start();
  }, [latest?.confidence]);

  useEffect(() => {
    if (isStale) return;
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(dotScale, { toValue: 1.6, duration: 800, useNativeDriver: true }),
        Animated.timing(dotScale, { toValue: 1, duration: 800, useNativeDriver: true }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [isStale]);

  const dirColor =
    direction === "BULLISH" ? C.green :
    direction === "BEARISH" ? C.red :
    C.accentBright;

  const iconBg =
    direction === "BULLISH" ? C.greenDark :
    direction === "BEARISH" ? C.redDark :
    C.accentLight;

  return (
    <Animated.View style={{ opacity, transform: [{ translateY }] }}>
      <Card style={[styles.agentCard, isStale ? styles.staleCard : null] as any}>
        <View style={styles.agentHeader}>
          <LinearGradient
            colors={direction === "BULLISH" ? C.gradient.profit : direction === "BEARISH" ? C.gradient.loss : C.gradient.accent}
            style={styles.agentIconWrap}
          >
            <Feather name={info.icon} size={16} color="#fff" />
          </LinearGradient>
          <View style={styles.agentInfo}>
            <Text style={styles.agentName}>{info.name}</Text>
            <Text style={styles.agentId}>{agentId.replace("_", " #")}</Text>
          </View>
          <View style={styles.agentBadges}>
            {direction ? (
              <StatusBadge label={direction} variant={dirVariant} />
            ) : (
              <StatusBadge label="Idle" variant="inactive" />
            )}
            <Animated.View style={[styles.activeDot, {
              backgroundColor: isStale ? C.textQuaternary : C.green,
              transform: [{ scale: dotScale }],
              shadowColor: isStale ? "transparent" : C.green,
            }]} />
          </View>
        </View>

        {latest && (
          <View style={styles.latestSignal}>
            <View style={styles.signalRow}>
              <Text style={styles.signalLabel}>Confidence</Text>
              <View style={styles.confBarOuter}>
                <Animated.View style={[styles.confBarInner, {
                  width: confBarWidth.interpolate({ inputRange: [0, 1], outputRange: ["0%", "100%"] }),
                  backgroundColor: dirColor,
                }]} />
              </View>
              <Text style={[styles.confValue, { color: dirColor }]}>
                {((latest.confidence ?? 0) * 100).toFixed(0)}%
              </Text>
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
              <Text style={styles.reasoning} numberOfLines={3}>{latest.reasoning}</Text>
            )}
          </View>
        )}

        {lastActive && (
          <View style={styles.lastActiveRow}>
            <Feather name="clock" size={10} color={C.textTertiary} />
            <Text style={styles.lastActive}>{formatTimeAgo(lastActive)}</Text>
          </View>
        )}
      </Card>
    </Animated.View>
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
  container: { flex: 1, backgroundColor: C.bg },
  content: { paddingHorizontal: 20, paddingTop: 12, paddingBottom: 100 },
  agentCard: { marginBottom: 10 },
  staleCard: { opacity: 0.65 },
  agentHeader: { flexDirection: "row", alignItems: "center" },
  agentIconWrap: {
    width: 38, height: 38, borderRadius: 12,
    justifyContent: "center", alignItems: "center", marginRight: 12,
  },
  agentInfo: { flex: 1 },
  agentName: { fontSize: 15, fontFamily: "Inter_600SemiBold", color: C.text },
  agentId: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary },
  agentBadges: { flexDirection: "row", alignItems: "center", gap: 8 },
  activeDot: {
    width: 8, height: 8, borderRadius: 4,
    shadowOffset: { width: 0, height: 0 }, shadowOpacity: 1, shadowRadius: 6,
  },
  latestSignal: { marginTop: 14, paddingTop: 14, borderTopWidth: 1, borderTopColor: C.separator },
  signalRow: { flexDirection: "row", alignItems: "center", marginBottom: 8 },
  signalLabel: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.textTertiary, width: 80 },
  signalValue: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.text, flex: 1 },
  confBarOuter: { flex: 1, height: 5, backgroundColor: C.elevated, borderRadius: 3, marginHorizontal: 10, overflow: "hidden" },
  confBarInner: { height: 5, borderRadius: 3 },
  confValue: { fontSize: 12, fontFamily: "Inter_700Bold", width: 36, textAlign: "right" },
  reasoning: { fontSize: 12, fontFamily: "Inter_400Regular", color: C.textSecondary, lineHeight: 18, marginTop: 4 },
  lastActiveRow: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: 10 },
  lastActive: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary },
});

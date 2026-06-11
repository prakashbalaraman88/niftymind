import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
} from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  withRepeat,
  withSequence,
  FadeInDown,
  interpolateColor,
  useAnimatedProps,
} from "react-native-reanimated";
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
  const barWidth = useSharedValue(0);
  const dotScale = useSharedValue(1);
  const dotOpacity = useSharedValue(isStale ? 0 : 1);
  const cardGlow = useSharedValue(0);

  const dirColor =
    direction === "BULLISH" ? C.green :
    direction === "BEARISH" ? C.red :
    C.accentBright;

  const glowColor =
    direction === "BULLISH" ? "rgba(0,200,100,0.12)" :
    direction === "BEARISH" ? "rgba(255,70,70,0.12)" :
    "rgba(100,120,255,0.10)";

  // Animate confidence bar when signal arrives
  useEffect(() => {
    const confidence = latest?.confidence ?? 0;
    barWidth.value = withTiming(confidence, { duration: 900 });
  }, [latest?.confidence]);

  // Pulse active dot when not stale
  useEffect(() => {
    dotOpacity.value = withTiming(isStale ? 0 : 1, { duration: 300 });
    if (!isStale) {
      dotScale.value = withRepeat(
        withSequence(
          withTiming(1.8, { duration: 700 }),
          withTiming(1, { duration: 700 })
        ),
        -1
      );
    } else {
      dotScale.value = withTiming(1, { duration: 300 });
    }
  }, [isStale]);

  // Glow pulse when active
  useEffect(() => {
    if (!isStale && latest) {
      cardGlow.value = withRepeat(
        withSequence(
          withTiming(1, { duration: 1800 }),
          withTiming(0.3, { duration: 1800 })
        ),
        -1
      );
    } else {
      cardGlow.value = withTiming(0, { duration: 400 });
    }
  }, [isStale, latest]);

  const barStyle = useAnimatedStyle(() => ({
    width: `${barWidth.value * 100}%` as any,
  }));

  const dotStyle = useAnimatedStyle(() => ({
    transform: [{ scale: dotScale.value }],
    opacity: dotOpacity.value,
  }));

  const glowStyle = useAnimatedStyle(() => ({
    opacity: cardGlow.value,
  }));

  const cardStyle = useAnimatedStyle(() => ({
    opacity: isStale ? 0.62 : 1,
  }));

  const iconGradient: [string, string] =
    direction === "BULLISH" ? (C.gradient?.profit as [string, string] ?? ["#00C864", "#00A050"]) :
    direction === "BEARISH" ? (C.gradient?.loss as [string, string] ?? ["#FF4646", "#CC2222"]) :
    (C.gradient?.accent as [string, string] ?? ["#6478FF", "#4455DD"]);

  return (
    <Animated.View
      entering={FadeInDown.delay(index * 60).springify().damping(14)}
      style={cardStyle}
    >
      <View style={styles.cardWrapper}>
        {/* Glow overlay */}
        {!isStale && latest && (
          <Animated.View
            style={[
              StyleSheet.absoluteFill,
              styles.glowOverlay,
              { backgroundColor: glowColor },
              glowStyle,
            ]}
            pointerEvents="none"
          />
        )}

        <Card style={styles.agentCard}>
          {/* Header row */}
          <View style={styles.agentHeader}>
            <LinearGradient
              colors={iconGradient}
              style={styles.agentIconWrap}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
            >
              <Feather name={info.icon} size={18} color="#fff" />
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
              <View style={styles.dotContainer}>
                <Animated.View
                  style={[
                    styles.activeDot,
                    {
                      backgroundColor: dirColor,
                      shadowColor: dirColor,
                    },
                    dotStyle,
                  ]}
                />
              </View>
            </View>
          </View>

          {/* Signal section */}
          {latest && (
            <View style={styles.latestSignal}>
              {/* Confidence bar */}
              <View style={styles.signalRow}>
                <Text style={styles.signalLabel}>Confidence</Text>
                <View style={styles.confBarOuter}>
                  <Animated.View
                    style={[
                      styles.confBarInner,
                      { backgroundColor: dirColor },
                      barStyle,
                    ]}
                  />
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
                <Text style={styles.reasoning} numberOfLines={3}>
                  {latest.reasoning}
                </Text>
              )}
            </View>
          )}

          {/* Footer */}
          {lastActive && (
            <View style={styles.lastActiveRow}>
              <Feather name="clock" size={10} color={C.textTertiary} />
              <Text style={styles.lastActive}>{formatTimeAgo(lastActive)}</Text>
            </View>
          )}
        </Card>
      </View>
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
  content: { paddingHorizontal: 20, paddingTop: 12, paddingBottom: 100, gap: 12 },
  cardWrapper: {
    borderRadius: 16,
    overflow: "hidden",
  },
  glowOverlay: {
    borderRadius: 16,
    zIndex: 1,
  },
  agentCard: { marginBottom: 0 },
  agentHeader: { flexDirection: "row", alignItems: "center" },
  agentIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    justifyContent: "center",
    alignItems: "center",
    marginRight: 12,
  },
  agentInfo: { flex: 1 },
  agentName: { fontSize: 15, fontFamily: "Inter_600SemiBold", color: C.text },
  agentId: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary, marginTop: 2 },
  agentBadges: { flexDirection: "row", alignItems: "center", gap: 8 },
  dotContainer: {
    width: 14,
    height: 14,
    justifyContent: "center",
    alignItems: "center",
  },
  activeDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 6,
  },
  latestSignal: {
    marginTop: 14,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: C.separator,
  },
  signalRow: { flexDirection: "row", alignItems: "center", marginBottom: 8 },
  signalLabel: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.textTertiary, width: 80 },
  signalValue: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.text, flex: 1 },
  confBarOuter: {
    flex: 1,
    height: 6,
    backgroundColor: C.elevated,
    borderRadius: 3,
    marginHorizontal: 10,
    overflow: "hidden",
  },
  confBarInner: { height: 6, borderRadius: 3 },
  confValue: { fontSize: 12, fontFamily: "Inter_700Bold", width: 36, textAlign: "right" },
  reasoning: {
    fontSize: 12,
    fontFamily: "Inter_400Regular",
    color: C.textSecondary,
    lineHeight: 18,
    marginTop: 4,
    fontStyle: "italic",
  },
  lastActiveRow: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: 10 },
  lastActive: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary },
});

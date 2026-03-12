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
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import colors from "@/constants/colors";
import { AGENT_INFO, AGENT_IDS } from "@/constants/agents";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "@/components/Card";
import { PnlText } from "@/components/PnlText";
import { StatusBadge } from "@/components/StatusBadge";
import { CardSkeleton } from "@/components/SkeletonLoader";
import { Confetti } from "@/components/Confetti";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import type { DashboardData, TickData } from "@/types/api";

const C = colors.dark;

export default function DashboardScreen() {
  const insets = useSafeAreaInsets();
  const { connected, ticks, subscribe } = useWebSocket();
  const queryClient = useQueryClient();
  const headerOpacity = useRef(new Animated.Value(0)).current;
  const headerY = useRef(new Animated.Value(-16)).current;
  const [showConfetti, setShowConfetti] = useState(false);
  const prevPnlRef = useRef<number>(0);

  const { data, isLoading, isError, refetch, isRefetching } = useQuery<DashboardData>({
    queryKey: ["dashboard"],
    queryFn: api.getDashboard,
    refetchInterval: 30000,
    retry: false,
  });

  useEffect(() => {
    Animated.parallel([
      Animated.timing(headerOpacity, { toValue: 1, duration: 600, useNativeDriver: true }),
      Animated.spring(headerY, { toValue: 0, useNativeDriver: true, damping: 16, mass: 0.9 }),
    ]).start();
  }, []);

  useEffect(() => {
    const unsub = subscribe("trade_execution", () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    });
    return unsub;
  }, [subscribe, queryClient]);

  const niftyTick = ticks["NIFTY 50"] || ticks["NIFTY"] || ticks["Nifty 50"];
  const bankNiftyTick = ticks["BANKNIFTY"] || ticks["BANK NIFTY"] || ticks["Bank Nifty"];
  const vixTick = ticks["INDIA VIX"] || ticks["VIX"] || ticks["India VIX"];

  const tradingMode = data?.trading_mode || "paper";
  const totalPnl = data?.executor?.today_pnl ?? data?.executor?.total_pnl ?? 0;
  const openPositions = data?.positions?.open || [];
  const capital = data?.capital ?? 500000;
  const vixHalt = data?.risk_limits?.vix_halt_threshold ?? 25;
  const vixValue = vixTick?.ltp ?? 0;
  const vixBreached = vixValue > 0 && vixValue > vixHalt;
  const totalTrades = data?.executor?.total_trades ?? 0;
  const pnlPct = capital > 0 ? (totalPnl / capital) * 100 : 0;

  useEffect(() => {
    if (totalPnl > 0 && prevPnlRef.current <= 0 && !isLoading) {
      setShowConfetti(true);
    }
    prevPnlRef.current = totalPnl;
  }, [totalPnl, isLoading]);

  return (
    <>
      <Confetti active={showConfetti} onComplete={() => setShowConfetti(false)} />
      <ScrollView
        style={styles.container}
        contentContainerStyle={{ paddingTop: insets.top + 16, paddingBottom: 100 }}
        refreshControl={
          <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={C.accentBright} />
        }
      >
        <Animated.View style={[styles.header, { opacity: headerOpacity, transform: [{ translateY: headerY }] }]}>
          <View>
            <Text style={styles.appTitle}>NiftyMind</Text>
            <View style={styles.statusRow}>
              <View style={[styles.liveDot, {
                backgroundColor: connected ? C.green : C.red,
                shadowColor: connected ? C.green : C.red,
              }]} />
              <Text style={styles.statusText}>{connected ? "Live" : "Offline"}</Text>
              <StatusBadge label={tradingMode} variant={tradingMode === "live" ? "live" : "paper"} />
            </View>
          </View>
        </Animated.View>

        {isLoading && !isError ? (
          <>
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </>
        ) : (
          <>
            <LinearGradient
              colors={[totalPnl >= 0 ? "rgba(16,240,160,0.08)" : "rgba(255,59,92,0.08)", "transparent"]}
              style={styles.pnlHero}
            >
              <Text style={styles.pnlLabel}>Today's P&L</Text>
              <AnimatedNumber
                value={totalPnl}
                prefix="₹"
                style={[
                  styles.pnlHeroValue,
                  {
                    color: totalPnl > 0 ? C.green : totalPnl < 0 ? C.red : C.textSecondary,
                    textShadowColor: totalPnl > 0 ? C.greenGlow : totalPnl < 0 ? C.redGlow : "transparent",
                    textShadowOffset: { width: 0, height: 0 },
                    textShadowRadius: 20,
                  },
                ] as any}
                formatFn={(v) => {
                  const sign = v > 0 ? "+" : "";
                  return `₹${sign}${Math.round(v).toLocaleString("en-IN")}`;
                }}
              />
              {pnlPct !== 0 && (
                <Text style={[styles.pnlPct, { color: totalPnl >= 0 ? C.green : C.red }]}>
                  {totalPnl >= 0 ? "+" : ""}{pnlPct.toFixed(2)}% return
                </Text>
              )}
              <View style={styles.pnlMeta}>
                <PnlMetaItem label="Capital" value={`₹${(capital / 1000).toFixed(0)}K`} />
                <View style={styles.pnlMetaDivider} />
                <PnlMetaItem label="Open" value={String(openPositions.length)} />
                <View style={styles.pnlMetaDivider} />
                <PnlMetaItem label="Trades" value={String(totalTrades)} />
              </View>
            </LinearGradient>

            <View style={styles.priceRow}>
              <PriceCard label="NIFTY 50" tick={niftyTick} />
              <PriceCard label="BANKNIFTY" tick={bankNiftyTick} />
            </View>

            <Card style={styles.vixCard}>
              <View style={styles.vixRow}>
                <View style={styles.vixLeft}>
                  <View style={[styles.vixIcon, { backgroundColor: vixBreached ? C.redDark : C.greenDark }]}>
                    <Feather name="activity" size={14} color={vixBreached ? C.red : C.green} />
                  </View>
                  <View>
                    <Text style={styles.vixLabel}>India VIX</Text>
                    <Text style={styles.vixSublabel}>Volatility Index</Text>
                  </View>
                </View>
                <View style={styles.vixRight}>
                  <Text style={[styles.vixValue, {
                    color: vixBreached ? C.red : C.text,
                    textShadowColor: vixBreached ? C.redGlow : "transparent",
                    textShadowRadius: 8,
                    textShadowOffset: { width: 0, height: 0 },
                  }]}>
                    {vixValue > 0 ? vixValue.toFixed(2) : "--"}
                  </Text>
                  <StatusBadge
                    label={vixBreached ? "HALT" : vixValue > 0 ? "OK" : "N/A"}
                    variant={vixBreached ? "high" : "low"}
                  />
                </View>
              </View>
              {vixValue > 0 && (
                <View style={styles.vixBarSection}>
                  <Text style={styles.vixThresholdText}>Halt at {vixHalt}</Text>
                  <View style={styles.vixBarOuter}>
                    <Animated.View style={[styles.vixBarInner, {
                      width: `${Math.min((vixValue / (vixHalt * 1.5)) * 100, 100)}%`,
                      backgroundColor: vixBreached ? C.red : C.green,
                    }]} />
                    <View style={[styles.vixThresholdMark, {
                      left: `${(vixHalt / (vixHalt * 1.5)) * 100}%`,
                    }]} />
                  </View>
                </View>
              )}
            </Card>

            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Agent Grid</Text>
              <View style={styles.sectionBadge}>
                <Text style={styles.sectionBadgeText}>12 AI</Text>
              </View>
            </View>
            <View style={styles.agentGrid}>
              {AGENT_IDS.map((id, i) => (
                <AgentCell key={id} agentId={id} index={i} />
              ))}
            </View>

            {openPositions.length > 0 && (
              <>
                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionTitle}>Open Positions</Text>
                  <Text style={styles.sectionCount}>{openPositions.length} active</Text>
                </View>
                {openPositions.map((pos) => (
                  <Card key={pos.trade_id} style={styles.positionCard}>
                    <View style={styles.posRow}>
                      <View style={styles.posLeft}>
                        <Text style={styles.posSymbol}>{pos.symbol}</Text>
                        <Text style={styles.posDetail}>
                          {pos.direction} · {pos.quantity} qty @ ₹{pos.entry_price?.toLocaleString("en-IN")}
                        </Text>
                      </View>
                      <PnlText
                        value={pos.unrealized_pnl ?? 0}
                        prefix="₹"
                        style={styles.posPnl}
                        animate
                      />
                    </View>
                  </Card>
                ))}
              </>
            )}
          </>
        )}
      </ScrollView>
    </>
  );
}

function PnlMetaItem({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.pnlMetaItem}>
      <Text style={styles.pnlMetaLabel}>{label}</Text>
      <Text style={styles.pnlMetaValue}>{value}</Text>
    </View>
  );
}

function PriceCard({ label, tick }: { label: string; tick?: TickData }) {
  const price = tick?.ltp ?? 0;
  const change = tick?.change_pct ?? 0;
  const isUp = change >= 0;
  const priceAnim = useRef(new Animated.Value(1)).current;

  const prevPrice = useRef(price);
  useEffect(() => {
    if (prevPrice.current !== price && price > 0) {
      prevPrice.current = price;
      Animated.sequence([
        Animated.timing(priceAnim, { toValue: 1.04, duration: 100, useNativeDriver: true }),
        Animated.timing(priceAnim, { toValue: 1, duration: 200, useNativeDriver: true }),
      ]).start();
    }
  }, [price]);

  return (
    <Card style={styles.priceCard}>
      <Text style={styles.priceLabel}>{label}</Text>
      <Animated.Text style={[styles.priceValue, { transform: [{ scale: priceAnim }] }]}>
        {price > 0 ? price.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : "--"}
      </Animated.Text>
      {price > 0 && (
        <View style={[styles.priceChangeRow, {
          backgroundColor: isUp ? C.greenDark : C.redDark,
        }]}>
          <Feather name={isUp ? "arrow-up-right" : "arrow-down-right"} size={11} color={isUp ? C.green : C.red} />
          <Text style={[styles.priceChangeText, { color: isUp ? C.green : C.red }]}>
            {Math.abs(change).toFixed(2)}%
          </Text>
        </View>
      )}
    </Card>
  );
}

function AgentCell({ agentId, index }: { agentId: string; index: number }) {
  const info = AGENT_INFO[agentId];
  const { subscribe } = useWebSocket();
  const [signal, setSignal] = useState<string>("--");
  const [active, setActive] = useState(false);
  const cellOpacity = useRef(new Animated.Value(0)).current;
  const dotScale = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    Animated.timing(cellOpacity, {
      toValue: 1,
      duration: 400,
      delay: index * 40,
      useNativeDriver: true,
    }).start();
  }, []);

  useEffect(() => {
    if (!active) return;
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(dotScale, { toValue: 1.6, duration: 700, useNativeDriver: true }),
        Animated.timing(dotScale, { toValue: 1, duration: 700, useNativeDriver: true }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [active]);

  useEffect(() => {
    const u1 = subscribe("signal", (data: any) => {
      if (data?.agent_id === agentId) {
        setSignal(data.direction || "--");
        setActive(true);
      }
    });
    const u2 = subscribe("agent_status", (data: any) => {
      if (data?.agent_id === agentId || data?.source === agentId) setActive(true);
    });
    return () => { u1(); u2(); };
  }, [agentId, subscribe]);

  const dirColor =
    signal === "BULLISH" ? C.green :
    signal === "BEARISH" ? C.red :
    C.textTertiary;

  return (
    <Animated.View style={[styles.agentCell, { opacity: cellOpacity }]}>
      <Animated.View style={[styles.agentActiveDot, {
        backgroundColor: active ? C.green : C.textQuaternary,
        transform: [{ scale: dotScale }],
        shadowColor: active ? C.green : "transparent",
      }]} />
      <Feather name={info?.icon ?? "cpu"} size={15} color={active ? dirColor : C.textTertiary} />
      <Text style={styles.agentName} numberOfLines={1}>{info?.shortName || agentId}</Text>
      <Text style={[styles.agentSignal, { color: dirColor }]} numberOfLines={1}>
        {signal === "--" ? "--" : signal.substring(0, 4)}
      </Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  header: { paddingHorizontal: 20, paddingBottom: 20 },
  appTitle: {
    fontSize: 30,
    fontFamily: "Inter_700Bold",
    color: C.text,
    letterSpacing: -1,
  },
  statusRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6 },
  liveDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 6,
  },
  statusText: { fontSize: 13, fontFamily: "Inter_400Regular", color: C.textSecondary },
  pnlHero: {
    marginHorizontal: 20,
    marginBottom: 16,
    borderRadius: 24,
    padding: 24,
    borderWidth: 1,
    borderColor: C.cardBorder,
  },
  pnlLabel: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.textSecondary, letterSpacing: 1, marginBottom: 8 },
  pnlHeroValue: { fontSize: 44, fontFamily: "Inter_700Bold", letterSpacing: -1.5, marginBottom: 4 },
  pnlPct: { fontSize: 14, fontFamily: "Inter_500Medium", marginBottom: 20 },
  pnlMeta: {
    flexDirection: "row",
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: C.separator,
    paddingTop: 16,
  },
  pnlMetaItem: { flex: 1, alignItems: "center" },
  pnlMetaLabel: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary, marginBottom: 4 },
  pnlMetaValue: { fontSize: 16, fontFamily: "Inter_600SemiBold", color: C.text },
  pnlMetaDivider: { width: 1, height: 30, backgroundColor: C.separator },
  priceRow: { flexDirection: "row", paddingHorizontal: 20, gap: 12, marginBottom: 12 },
  priceCard: { flex: 1 },
  priceLabel: { fontSize: 11, fontFamily: "Inter_500Medium", color: C.textSecondary, marginBottom: 6, letterSpacing: 0.5 },
  priceValue: { fontSize: 22, fontFamily: "Inter_700Bold", color: C.text, letterSpacing: -0.5 },
  priceChangeRow: {
    flexDirection: "row", alignItems: "center", gap: 3, marginTop: 8,
    paddingHorizontal: 6, paddingVertical: 3, borderRadius: 6, alignSelf: "flex-start",
  },
  priceChangeText: { fontSize: 11, fontFamily: "Inter_600SemiBold" },
  vixCard: { marginHorizontal: 20, marginBottom: 16 },
  vixRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  vixLeft: { flexDirection: "row", alignItems: "center", gap: 10 },
  vixIcon: {
    width: 34, height: 34, borderRadius: 10,
    justifyContent: "center", alignItems: "center",
  },
  vixLabel: { fontSize: 14, fontFamily: "Inter_600SemiBold", color: C.text },
  vixSublabel: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary },
  vixRight: { flexDirection: "row", alignItems: "center", gap: 10 },
  vixValue: { fontSize: 22, fontFamily: "Inter_700Bold" },
  vixBarSection: { marginTop: 14 },
  vixThresholdText: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary, marginBottom: 6 },
  vixBarOuter: { height: 5, backgroundColor: C.elevated, borderRadius: 3, overflow: "visible" as const, position: "relative" as const },
  vixBarInner: { height: 5, borderRadius: 3 },
  vixThresholdMark: { position: "absolute" as const, top: -3, width: 2, height: 11, backgroundColor: C.red, borderRadius: 1 },
  sectionHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 20, marginTop: 4, marginBottom: 12 },
  sectionTitle: { fontSize: 17, fontFamily: "Inter_600SemiBold", color: C.text },
  sectionBadge: { backgroundColor: C.accentLight, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 3 },
  sectionBadgeText: { fontSize: 11, fontFamily: "Inter_600SemiBold", color: C.accentBright },
  sectionCount: { fontSize: 13, fontFamily: "Inter_400Regular", color: C.textSecondary },
  agentGrid: { flexDirection: "row", flexWrap: "wrap", paddingHorizontal: 16, gap: 8, marginBottom: 16 },
  agentCell: {
    width: "22.5%",
    backgroundColor: C.card,
    borderRadius: 14,
    padding: 10,
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderColor: C.cardBorder,
  },
  agentActiveDot: {
    width: 6, height: 6, borderRadius: 3,
    position: "absolute", top: 7, right: 7,
    shadowOffset: { width: 0, height: 0 }, shadowOpacity: 1, shadowRadius: 6,
  },
  agentName: { fontSize: 10, fontFamily: "Inter_500Medium", color: C.textSecondary, textAlign: "center" },
  agentSignal: { fontSize: 9, fontFamily: "Inter_600SemiBold", letterSpacing: 0.3 },
  positionCard: { marginHorizontal: 20, marginBottom: 8 },
  posRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  posLeft: { flex: 1 },
  posSymbol: { fontSize: 15, fontFamily: "Inter_600SemiBold", color: C.text },
  posDetail: { fontSize: 12, fontFamily: "Inter_400Regular", color: C.textSecondary, marginTop: 2 },
  posPnl: { fontSize: 16 },
});

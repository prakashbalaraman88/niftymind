import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
} from "react-native";
import { Feather } from "@expo/vector-icons";
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
import type { DashboardData, TickData } from "@/types/api";

export default function DashboardScreen() {
  const insets = useSafeAreaInsets();
  const { connected, ticks, subscribe } = useWebSocket();
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch, isRefetching } = useQuery<DashboardData>({
    queryKey: ["dashboard"],
    queryFn: api.getDashboard,
    refetchInterval: 30000,
    retry: false,
  });

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

  return (
    <ScrollView
      style={[styles.container]}
      contentContainerStyle={{ paddingTop: insets.top + 8, paddingBottom: 100 }}
      contentInsetAdjustmentBehavior="automatic"
      refreshControl={
        <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={colors.light.tint} />
      }
    >
      <View style={styles.header}>
        <View>
          <Text style={styles.appTitle}>NiftyMind</Text>
          <View style={styles.statusRow}>
            <View style={[styles.dot, { backgroundColor: connected ? colors.light.green : colors.light.red }]} />
            <Text style={styles.statusText}>{connected ? "Live" : "Offline"}</Text>
            <StatusBadge label={tradingMode} variant={tradingMode === "live" ? "live" : "paper"} />
          </View>
        </View>
      </View>

      {isLoading && !isError ? (
        <>
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </>
      ) : (
        <>
          <View style={styles.priceRow}>
            <PriceCard label="NIFTY 50" tick={niftyTick} />
            <PriceCard label="BANKNIFTY" tick={bankNiftyTick} />
          </View>

          <Card style={styles.vixCard}>
            <View style={styles.vixRow}>
              <View style={styles.vixLeft}>
                <Feather name="activity" size={16} color={vixBreached ? colors.light.red : colors.light.green} />
                <Text style={styles.vixLabel}>India VIX</Text>
              </View>
              <View style={styles.vixRight}>
                <Text style={[styles.vixValue, { color: vixBreached ? colors.light.red : colors.light.text }]}>
                  {vixValue > 0 ? vixValue.toFixed(2) : "--"}
                </Text>
                <StatusBadge
                  label={vixBreached ? "HALT" : vixValue > 0 ? "OK" : "N/A"}
                  variant={vixBreached ? "high" : "low"}
                  size="small"
                />
              </View>
            </View>
            <View style={styles.vixThresholdRow}>
              <Text style={styles.vixThresholdText}>Halt threshold: {vixHalt}</Text>
              {vixValue > 0 && (
                <View style={styles.vixBarOuter}>
                  <View style={[
                    styles.vixBarInner,
                    {
                      width: `${Math.min((vixValue / (vixHalt * 1.5)) * 100, 100)}%`,
                      backgroundColor: vixBreached ? colors.light.red : colors.light.green,
                    },
                  ]} />
                  <View style={[styles.vixBarThreshold, { left: `${(vixHalt / (vixHalt * 1.5)) * 100}%` }]} />
                </View>
              )}
            </View>
          </Card>

          <Card style={styles.pnlCard}>
            <Text style={styles.cardLabel}>Today's P&L</Text>
            <PnlText value={totalPnl} prefix={"\u20B9"} style={styles.pnlValue} />
            <View style={styles.pnlMeta}>
              <View style={styles.pnlItem}>
                <Text style={styles.pnlItemLabel}>Capital</Text>
                <Text style={styles.pnlItemValue}>{"\u20B9"}{capital.toLocaleString("en-IN")}</Text>
              </View>
              <View style={styles.pnlDivider} />
              <View style={styles.pnlItem}>
                <Text style={styles.pnlItemLabel}>Open</Text>
                <Text style={styles.pnlItemValue}>{openPositions.length}</Text>
              </View>
              <View style={styles.pnlDivider} />
              <View style={styles.pnlItem}>
                <Text style={styles.pnlItemLabel}>Trades</Text>
                <Text style={styles.pnlItemValue}>{data?.executor?.total_trades ?? 0}</Text>
              </View>
            </View>
          </Card>

          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Agent Grid</Text>
            <Text style={styles.sectionSubtitle}>12 AI Agents</Text>
          </View>
          <View style={styles.agentGrid}>
            {AGENT_IDS.map((id) => (
              <AgentCell key={id} agentId={id} />
            ))}
          </View>

          {openPositions.length > 0 && (
            <>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Open Positions</Text>
                <Text style={styles.sectionSubtitle}>{openPositions.length} active</Text>
              </View>
              {openPositions.map((pos) => (
                <Card key={pos.trade_id} style={styles.positionCard}>
                  <View style={styles.posRow}>
                    <View>
                      <Text style={styles.posSymbol}>{pos.symbol}</Text>
                      <Text style={styles.posDetail}>
                        {pos.direction} {pos.quantity} @ {"\u20B9"}{pos.entry_price?.toLocaleString("en-IN")}
                      </Text>
                    </View>
                    <PnlText value={pos.unrealized_pnl ?? 0} prefix={"\u20B9"} style={styles.posPnl} />
                  </View>
                </Card>
              ))}
            </>
          )}
        </>
      )}
    </ScrollView>
  );
}

function PriceCard({ label, tick }: { label: string; tick?: TickData }) {
  const price = tick?.ltp ?? 0;
  const change = tick?.change_pct ?? 0;
  const isUp = change >= 0;

  return (
    <Card style={styles.priceCard}>
      <Text style={styles.priceLabel}>{label}</Text>
      <Text style={styles.priceValue}>
        {price > 0 ? price.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : "--"}
      </Text>
      {price > 0 && (
        <View style={[styles.changeRow, { backgroundColor: isUp ? colors.light.greenLight : colors.light.redLight }]}>
          <Feather name={isUp ? "arrow-up-right" : "arrow-down-right"} size={12} color={isUp ? colors.light.green : colors.light.red} />
          <Text style={[styles.changeText, { color: isUp ? colors.light.green : colors.light.red }]}>
            {Math.abs(change).toFixed(2)}%
          </Text>
        </View>
      )}
    </Card>
  );
}

function AgentCell({ agentId }: { agentId: string }) {
  const info = AGENT_INFO[agentId];
  const { subscribe } = useWebSocket();
  const [signal, setSignal] = useState<string>("--");
  const [active, setActive] = useState(false);

  useEffect(() => {
    const unsub1 = subscribe("signal", (data: any) => {
      if (data?.agent_id === agentId) {
        setSignal(data.direction || "--");
        setActive(true);
      }
    });
    const unsub2 = subscribe("agent_status", (data: any) => {
      if (data?.agent_id === agentId || data?.source === agentId) {
        setActive(true);
      }
    });
    return () => { unsub1(); unsub2(); };
  }, [agentId, subscribe]);

  const dirColor =
    signal === "BULLISH" ? colors.light.green :
    signal === "BEARISH" ? colors.light.red :
    colors.light.textTertiary;

  return (
    <View style={styles.agentCell}>
      <View style={[styles.agentDot, { backgroundColor: active ? colors.light.green : "#D1D5DB" }]} />
      <Feather name={info?.icon ?? "cpu"} size={16} color={dirColor} />
      <Text style={styles.agentName} numberOfLines={1}>{info?.shortName || agentId}</Text>
      <Text style={[styles.agentSignal, { color: dirColor }]} numberOfLines={1}>
        {signal === "--" ? "--" : signal.substring(0, 4)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.light.background,
  },
  header: {
    paddingHorizontal: 20,
    paddingBottom: 16,
  },
  appTitle: {
    fontSize: 28,
    fontFamily: "Inter_700Bold",
    color: colors.light.text,
    letterSpacing: -0.5,
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  statusText: {
    fontSize: 13,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
  },
  priceRow: {
    flexDirection: "row",
    paddingHorizontal: 20,
    gap: 12,
    marginBottom: 12,
  },
  priceCard: {
    flex: 1,
  },
  priceLabel: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
    marginBottom: 4,
    letterSpacing: 0.3,
  },
  priceValue: {
    fontSize: 22,
    fontFamily: "Inter_700Bold",
    color: colors.light.text,
    letterSpacing: -0.3,
  },
  changeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    marginTop: 6,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 6,
    alignSelf: "flex-start" as const,
  },
  changeText: {
    fontSize: 12,
    fontFamily: "Inter_600SemiBold",
  },
  vixCard: {
    marginHorizontal: 20,
    marginBottom: 12,
    padding: 14,
  },
  vixRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  vixLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  vixLabel: {
    fontSize: 14,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  vixRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  vixValue: {
    fontSize: 18,
    fontFamily: "Inter_700Bold",
  },
  vixThresholdRow: {
    marginTop: 8,
  },
  vixThresholdText: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: colors.light.textTertiary,
    marginBottom: 4,
  },
  vixBarOuter: {
    height: 4,
    backgroundColor: colors.light.border,
    borderRadius: 2,
    overflow: "visible",
    position: "relative" as const,
  },
  vixBarInner: {
    height: 4,
    borderRadius: 2,
  },
  vixBarThreshold: {
    position: "absolute" as const,
    top: -2,
    width: 2,
    height: 8,
    backgroundColor: colors.light.red,
    borderRadius: 1,
  },
  pnlCard: {
    marginHorizontal: 20,
    marginBottom: 12,
  },
  cardLabel: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
    marginBottom: 4,
    letterSpacing: 0.3,
  },
  pnlValue: {
    fontSize: 32,
    letterSpacing: -0.5,
    marginBottom: 12,
  },
  pnlMeta: {
    flexDirection: "row",
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: colors.light.border,
    paddingTop: 12,
  },
  pnlItem: {
    flex: 1,
    alignItems: "center",
  },
  pnlDivider: {
    width: 1,
    height: 28,
    backgroundColor: colors.light.border,
  },
  pnlItemLabel: {
    fontSize: 11,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
    marginBottom: 2,
  },
  pnlItemValue: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
    paddingHorizontal: 20,
    marginTop: 8,
    marginBottom: 10,
  },
  sectionTitle: {
    fontSize: 17,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  sectionSubtitle: {
    fontSize: 13,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
  },
  agentGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    paddingHorizontal: 16,
    gap: 8,
    marginBottom: 12,
  },
  agentCell: {
    width: "22.5%",
    backgroundColor: colors.light.surface,
    borderRadius: 12,
    padding: 10,
    alignItems: "center",
    gap: 4,
    shadowColor: colors.light.cardShadow,
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 1,
    shadowRadius: 4,
    elevation: 1,
  },
  agentDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    position: "absolute",
    top: 6,
    right: 6,
  },
  agentName: {
    fontSize: 10,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
    textAlign: "center",
  },
  agentSignal: {
    fontSize: 9,
    fontFamily: "Inter_600SemiBold",
    letterSpacing: 0.3,
  },
  positionCard: {
    marginHorizontal: 20,
    marginBottom: 8,
  },
  posRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  posSymbol: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  posDetail: {
    fontSize: 12,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
    marginTop: 2,
  },
  posPnl: {
    fontSize: 16,
  },
});

import React, { useState, useCallback, useEffect, useRef } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  RefreshControl,
  ActivityIndicator,
  Animated,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import colors from "@/constants/colors";
import { AGENT_INFO } from "@/constants/agents";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "@/components/Card";
import { PnlText } from "@/components/PnlText";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { Confetti } from "@/components/Confetti";
import type { Trade, TradeDetail, AgentVote } from "@/types/api";

const C = colors.dark;
type FilterStatus = "all" | "OPEN" | "CLOSED" | "CANCELLED";
const FILTERS: { key: FilterStatus; label: string }[] = [
  { key: "all", label: "All" },
  { key: "OPEN", label: "Open" },
  { key: "CLOSED", label: "Closed" },
  { key: "CANCELLED", label: "Cancelled" },
];

export default function TradesScreen() {
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showConfetti, setShowConfetti] = useState(false);
  const { subscribe } = useWebSocket();
  const queryClient = useQueryClient();

  const { data, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ["trades", filter],
    queryFn: () => api.getTrades(100, 0, filter === "all" ? undefined : filter),
    retry: false,
  });

  useEffect(() => {
    const unsub = subscribe("trade_execution", (evt: any) => {
      queryClient.invalidateQueries({ queryKey: ["trades"] });
      if (evt?.status === "CLOSED" && (evt?.pnl ?? 0) > 0) {
        setShowConfetti(true);
      }
    });
    return unsub;
  }, [subscribe, queryClient]);

  const trades = data?.trades || [];

  const renderItem = useCallback(
    ({ item, index }: { item: Trade; index: number }) => (
      <TradeRow
        trade={item}
        index={index}
        isExpanded={expandedId === item.trade_id}
        onToggle={() => setExpandedId((prev) => (prev === item.trade_id ? null : item.trade_id))}
      />
    ),
    [expandedId]
  );

  return (
    <>
      <Confetti active={showConfetti} onComplete={() => setShowConfetti(false)} />
      <View style={styles.container}>
        <View style={styles.filterBar}>
          {FILTERS.map((f) => (
            <Pressable key={f.key} onPress={() => setFilter(f.key)} style={styles.filterBtnWrap}>
              {filter === f.key ? (
                <LinearGradient
                  colors={C.gradient.accent}
                  start={{ x: 0, y: 0 }}
                  end={{ x: 1, y: 0 }}
                  style={styles.filterBtnActive}
                >
                  <Text style={styles.filterTextActive}>{f.label}</Text>
                </LinearGradient>
              ) : (
                <View style={styles.filterBtn}>
                  <Text style={styles.filterText}>{f.label}</Text>
                </View>
              )}
            </Pressable>
          ))}
        </View>

        <FlatList
          data={trades}
          keyExtractor={(item) => item.trade_id}
          renderItem={renderItem}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={C.accentBright} />
          }
          ListEmptyComponent={
            isLoading ? (
              <ActivityIndicator color={C.accentBright} style={{ marginTop: 60 }} />
            ) : (
              <EmptyState
                icon="inbox"
                title="No trades yet"
                subtitle="Trades will appear here when the system executes orders."
              />
            )
          }
        />
      </View>
    </>
  );
}

function TradeRow({
  trade,
  index,
  isExpanded,
  onToggle,
}: {
  trade: Trade;
  index: number;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const rowOpacity = useRef(new Animated.Value(0)).current;
  const rowY = useRef(new Animated.Value(16)).current;
  const dirVariant = trade.direction === "BULLISH" || trade.direction === "BUY" ? "bullish" : "bearish";
  const isProfitable = (trade.pnl ?? 0) > 0;
  const isClosed = trade.status === "CLOSED";

  useEffect(() => {
    Animated.parallel([
      Animated.timing(rowOpacity, { toValue: 1, duration: 400, delay: index * 50, useNativeDriver: true }),
      Animated.spring(rowY, { toValue: 0, delay: index * 50, useNativeDriver: true, damping: 16 }),
    ]).start();
  }, []);

  const statusColor =
    trade.status === "OPEN" ? C.accentBright :
    trade.status === "CLOSED" ? C.green :
    C.textTertiary;

  return (
    <Animated.View style={{ opacity: rowOpacity, transform: [{ translateY: rowY }] }}>
      <Card style={[
        styles.tradeCard,
        isClosed && isProfitable ? { borderColor: "rgba(16,240,160,0.15)" } : null,
      ] as any}>
        {isClosed && isProfitable && (
          <LinearGradient
            colors={["rgba(16,240,160,0.05)", "transparent"]}
            style={StyleSheet.absoluteFill}
            pointerEvents="none"
          />
        )}
        <Pressable onPress={onToggle} style={styles.tradeHeader}>
          <View style={styles.tradeLeft}>
            <View style={styles.tradeSymbolRow}>
              <Text style={styles.tradeSymbol}>{trade.symbol}</Text>
              <StatusBadge label={trade.direction} variant={dirVariant} />
            </View>
            <Text style={styles.tradeMeta}>
              {trade.trade_type} · {trade.quantity} qty ·{" "}
              <Text style={{ color: statusColor }}>{trade.status}</Text>
            </Text>
          </View>
          <View style={styles.tradeRight}>
            {trade.pnl != null ? (
              <PnlText value={trade.pnl} prefix="₹" style={styles.tradePnl} />
            ) : (
              <Text style={styles.tradePrice}>₹{trade.entry_price?.toLocaleString("en-IN")}</Text>
            )}
            <Feather
              name={isExpanded ? "chevron-up" : "chevron-down"}
              size={16}
              color={C.textTertiary}
            />
          </View>
        </Pressable>
        {!!isExpanded && <TradeExpanded tradeId={trade.trade_id} trade={trade} />}
      </Card>
    </Animated.View>
  );
}

function TradeExpanded({ tradeId, trade }: { tradeId: string; trade: Trade }) {
  const { data, isLoading } = useQuery<TradeDetail>({
    queryKey: ["trade-detail", tradeId],
    queryFn: () => api.getTradeDetail(tradeId),
    retry: false,
  });

  if (isLoading) {
    return (
      <View style={styles.expandedLoading}>
        <ActivityIndicator color={C.accentBright} size="small" />
      </View>
    );
  }

  const votes = data?.agent_votes || [];

  return (
    <View style={styles.expanded}>
      <View style={styles.expandedDivider} />
      <View style={styles.priceGrid}>
        <PriceItem label="Entry" value={trade.entry_price} />
        <PriceItem label="SL" value={trade.sl_price} color={C.red} />
        <PriceItem label="Target" value={trade.target_price} color={C.green} />
        {trade.exit_price != null && <PriceItem label="Exit" value={trade.exit_price} />}
      </View>
      {trade.consensus_score != null && (
        <View style={styles.consensusRow}>
          <Text style={styles.consensusLabel}>Consensus</Text>
          <View style={styles.consensusBarOuter}>
            <View style={[styles.consensusBarInner, { width: `${trade.consensus_score * 100}%` }]} />
          </View>
          <Text style={styles.consensusValue}>{(trade.consensus_score * 100).toFixed(0)}%</Text>
        </View>
      )}
      {trade.exit_reason && (
        <View style={styles.exitReasonRow}>
          <Feather name="log-out" size={12} color={C.textSecondary} />
          <Text style={styles.exitReasonText}>{trade.exit_reason}</Text>
        </View>
      )}
      {votes.length > 0 && (
        <>
          <Text style={styles.votesTitle}>Agent Votes</Text>
          {votes.map((vote) => <VoteRow key={vote.agent_id} vote={vote} />)}
        </>
      )}
    </View>
  );
}

function PriceItem({ label, value, color }: { label: string; value?: number; color?: string }) {
  return (
    <View style={styles.priceItem}>
      <Text style={styles.priceItemLabel}>{label}</Text>
      <Text style={[styles.priceItemValue, color ? { color } : null]}>
        ₹{value?.toLocaleString("en-IN") ?? "--"}
      </Text>
    </View>
  );
}

function VoteRow({ vote }: { vote: AgentVote }) {
  const info = AGENT_INFO[vote.agent_id];
  const dirColor =
    vote.direction === "BULLISH" ? C.green :
    vote.direction === "BEARISH" ? C.red :
    C.textSecondary;

  return (
    <View style={styles.voteRow}>
      <View style={styles.voteTop}>
        <View style={styles.voteLeft}>
          <Feather name={info?.icon ?? "cpu"} size={13} color={dirColor} />
          <Text style={styles.voteName}>{info?.name || vote.agent_id}</Text>
        </View>
        <View style={styles.voteRight}>
          <View style={styles.voteConfBar}>
            <View style={[styles.voteConfFill, { width: `${vote.confidence * 100}%`, backgroundColor: dirColor }]} />
          </View>
          <Text style={[styles.voteDir, { color: dirColor }]}>{vote.direction?.substring(0, 4)}</Text>
          <Text style={styles.voteConf}>{(vote.confidence * 100).toFixed(0)}%</Text>
        </View>
      </View>
      {!!vote.reasoning && (
        <Text style={styles.voteReasoning} numberOfLines={3}>{vote.reasoning}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  filterBar: { flexDirection: "row", paddingHorizontal: 20, paddingVertical: 12, gap: 8 },
  filterBtnWrap: {},
  filterBtn: {
    paddingHorizontal: 16, paddingVertical: 7,
    borderRadius: 20, backgroundColor: C.card,
    borderWidth: 1, borderColor: C.cardBorder,
  },
  filterBtnActive: { paddingHorizontal: 16, paddingVertical: 7, borderRadius: 20 },
  filterText: { fontSize: 13, fontFamily: "Inter_500Medium", color: C.textSecondary },
  filterTextActive: { fontSize: 13, fontFamily: "Inter_600SemiBold", color: "#fff" },
  list: { paddingHorizontal: 20, paddingBottom: 100 },
  tradeCard: { marginBottom: 10, padding: 14, overflow: "hidden" },
  tradeHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  tradeLeft: { flex: 1, marginRight: 12 },
  tradeSymbolRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  tradeSymbol: { fontSize: 15, fontFamily: "Inter_600SemiBold", color: C.text },
  tradeMeta: { fontSize: 12, fontFamily: "Inter_400Regular", color: C.textSecondary },
  tradeRight: { alignItems: "flex-end", gap: 6 },
  tradePnl: { fontSize: 15 },
  tradePrice: { fontSize: 14, fontFamily: "Inter_500Medium", color: C.text },
  expandedLoading: { paddingVertical: 16, alignItems: "center" },
  expanded: { marginTop: 12 },
  expandedDivider: { height: 1, backgroundColor: C.separator, marginBottom: 12 },
  priceGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  priceItem: { backgroundColor: C.elevated, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  priceItemLabel: { fontSize: 10, fontFamily: "Inter_500Medium", color: C.textTertiary, marginBottom: 3 },
  priceItemValue: { fontSize: 13, fontFamily: "Inter_600SemiBold", color: C.text },
  consensusRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 10 },
  consensusLabel: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.textSecondary, width: 80 },
  consensusBarOuter: { flex: 1, height: 5, backgroundColor: C.elevated, borderRadius: 3, overflow: "hidden" },
  consensusBarInner: { height: 5, borderRadius: 3, backgroundColor: C.accentBright },
  consensusValue: { fontSize: 12, fontFamily: "Inter_700Bold", color: C.accentBright, width: 36, textAlign: "right" },
  exitReasonRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 10 },
  exitReasonText: { fontSize: 12, fontFamily: "Inter_400Regular", color: C.textSecondary },
  votesTitle: { fontSize: 12, fontFamily: "Inter_600SemiBold", color: C.textSecondary, marginBottom: 8, letterSpacing: 0.5 },
  voteRow: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: C.separator },
  voteTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  voteLeft: { flexDirection: "row", alignItems: "center", gap: 6, flex: 1 },
  voteName: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.text },
  voteRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  voteConfBar: { width: 44, height: 4, backgroundColor: C.elevated, borderRadius: 2, overflow: "hidden" },
  voteConfFill: { height: 4, borderRadius: 2 },
  voteDir: { fontSize: 10, fontFamily: "Inter_600SemiBold", width: 30, textAlign: "right" },
  voteConf: { fontSize: 11, fontFamily: "Inter_500Medium", color: C.textSecondary, width: 28, textAlign: "right" },
  voteReasoning: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary, lineHeight: 16, marginTop: 5, paddingLeft: 18 },
});

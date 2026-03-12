import React, { useState, useCallback, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import colors from "@/constants/colors";
import { AGENT_INFO } from "@/constants/agents";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "@/components/Card";
import { PnlText } from "@/components/PnlText";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import type { Trade, TradeDetail, AgentVote } from "@/types/api";

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
  const { subscribe } = useWebSocket();
  const queryClient = useQueryClient();

  const { data, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ["trades", filter],
    queryFn: () => api.getTrades(100, 0, filter === "all" ? undefined : filter),
    retry: false,
  });

  useEffect(() => {
    const unsub = subscribe("trade_execution", () => {
      queryClient.invalidateQueries({ queryKey: ["trades"] });
    });
    return unsub;
  }, [subscribe, queryClient]);

  const trades = data?.trades || [];

  const renderItem = useCallback(
    ({ item }: { item: Trade }) => (
      <TradeRow
        trade={item}
        isExpanded={expandedId === item.trade_id}
        onToggle={() => setExpandedId((prev) => (prev === item.trade_id ? null : item.trade_id))}
      />
    ),
    [expandedId]
  );

  return (
    <View style={styles.container}>
      <View style={styles.filterRow}>
        {FILTERS.map((f) => (
          <Pressable
            key={f.key}
            onPress={() => setFilter(f.key)}
            style={[styles.filterBtn, filter === f.key && styles.filterBtnActive]}
          >
            <Text style={[styles.filterText, filter === f.key && styles.filterTextActive]}>
              {f.label}
            </Text>
          </Pressable>
        ))}
      </View>

      <FlatList
        data={trades}
        keyExtractor={(item) => item.trade_id}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        contentInsetAdjustmentBehavior="automatic"
        refreshControl={
          <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={colors.light.tint} />
        }
        ListEmptyComponent={
          isLoading ? (
            <ActivityIndicator color={colors.light.tint} style={{ marginTop: 40 }} />
          ) : (
            <EmptyState icon="inbox" title="No trades yet" subtitle="Trades will appear here when the system executes orders." />
          )
        }
      />
    </View>
  );
}

function TradeRow({ trade, isExpanded, onToggle }: { trade: Trade; isExpanded: boolean; onToggle: () => void }) {
  const dirVariant = trade.direction === "BULLISH" || trade.direction === "BUY" ? "bullish" : "bearish";
  const statusColor =
    trade.status === "OPEN" ? colors.light.tint :
    trade.status === "CLOSED" ? colors.light.green :
    colors.light.textSecondary;

  return (
    <Card style={styles.tradeCard}>
      <Pressable onPress={onToggle} style={styles.tradeHeader}>
        <View style={styles.tradeLeft}>
          <View style={styles.tradeSymbolRow}>
            <Text style={styles.tradeSymbol}>{trade.symbol}</Text>
            <StatusBadge label={trade.direction} variant={dirVariant} />
          </View>
          <Text style={styles.tradeMeta}>
            {trade.trade_type} {"\u00B7"} {trade.quantity} qty {"\u00B7"}{" "}
            <Text style={{ color: statusColor }}>{trade.status}</Text>
          </Text>
        </View>
        <View style={styles.tradeRight}>
          {trade.pnl != null ? (
            <PnlText value={trade.pnl} prefix={"\u20B9"} style={styles.tradePnl} />
          ) : (
            <Text style={styles.tradePrice}>{"\u20B9"}{trade.entry_price?.toLocaleString("en-IN")}</Text>
          )}
          <Feather name={isExpanded ? "chevron-up" : "chevron-down"} size={16} color={colors.light.textTertiary} />
        </View>
      </Pressable>

      {!!isExpanded && <TradeExpanded tradeId={trade.trade_id} trade={trade} />}
    </Card>
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
        <ActivityIndicator color={colors.light.tint} size="small" />
      </View>
    );
  }

  const votes = data?.agent_votes || [];

  return (
    <View style={styles.expanded}>
      <View style={styles.expandedDivider} />

      <View style={styles.priceGrid}>
        <PriceItem label="Entry" value={trade.entry_price} />
        <PriceItem label="SL" value={trade.sl_price} color={colors.light.red} />
        <PriceItem label="Target" value={trade.target_price} color={colors.light.green} />
        {trade.exit_price != null && <PriceItem label="Exit" value={trade.exit_price} />}
      </View>

      {trade.consensus_score != null && (
        <View style={styles.consensusRow}>
          <Text style={styles.consensusLabel}>Consensus Score</Text>
          <Text style={styles.consensusValue}>{(trade.consensus_score * 100).toFixed(0)}%</Text>
        </View>
      )}

      {trade.exit_reason && (
        <View style={styles.exitReasonRow}>
          <Feather name="log-out" size={13} color={colors.light.textSecondary} />
          <Text style={styles.exitReasonText}>Exit: {trade.exit_reason}</Text>
        </View>
      )}

      {votes.length > 0 && (
        <>
          <Text style={styles.votesTitle}>Agent Votes</Text>
          {votes.map((vote) => (
            <VoteRow key={vote.agent_id} vote={vote} />
          ))}
        </>
      )}
    </View>
  );
}

function PriceItem({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <View style={styles.priceItem}>
      <Text style={styles.priceItemLabel}>{label}</Text>
      <Text style={[styles.priceItemValue, color ? { color } : null]}>
        {"\u20B9"}{value?.toLocaleString("en-IN")}
      </Text>
    </View>
  );
}

function VoteRow({ vote }: { vote: AgentVote }) {
  const info = AGENT_INFO[vote.agent_id];
  const dirColor =
    vote.direction === "BULLISH" ? colors.light.green :
    vote.direction === "BEARISH" ? colors.light.red :
    colors.light.textSecondary;

  return (
    <View style={styles.voteRow}>
      <View style={styles.voteTop}>
        <View style={styles.voteLeft}>
          <Feather name={info?.icon as any || "cpu"} size={14} color={dirColor} />
          <Text style={styles.voteName}>{info?.name || vote.agent_id}</Text>
        </View>
        <View style={styles.voteRight}>
          <View style={[styles.voteConfBar]}>
            <View style={[styles.voteConfFill, { width: `${vote.confidence * 100}%`, backgroundColor: dirColor }]} />
          </View>
          <Text style={[styles.voteDir, { color: dirColor }]}>{vote.direction}</Text>
          <Text style={styles.voteConf}>{(vote.confidence * 100).toFixed(0)}%</Text>
        </View>
      </View>
      {!!vote.reasoning && (
        <Text style={styles.voteReasoning} numberOfLines={3}>
          {vote.reasoning}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.light.background,
  },
  filterRow: {
    flexDirection: "row",
    paddingHorizontal: 20,
    paddingVertical: 12,
    gap: 8,
  },
  filterBtn: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 20,
    backgroundColor: colors.light.surface,
  },
  filterBtnActive: {
    backgroundColor: colors.light.text,
  },
  filterText: {
    fontSize: 13,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
  },
  filterTextActive: {
    color: "#fff",
  },
  list: {
    paddingHorizontal: 20,
    paddingBottom: 100,
  },
  tradeCard: {
    marginBottom: 10,
    padding: 14,
  },
  tradeHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  tradeLeft: {
    flex: 1,
    marginRight: 12,
  },
  tradeSymbolRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 4,
  },
  tradeSymbol: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  tradeMeta: {
    fontSize: 12,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
  },
  tradeRight: {
    alignItems: "flex-end",
    gap: 4,
  },
  tradePnl: {
    fontSize: 15,
  },
  tradePrice: {
    fontSize: 14,
    fontFamily: "Inter_500Medium",
    color: colors.light.text,
  },
  expandedLoading: {
    paddingVertical: 16,
    alignItems: "center",
  },
  expanded: {
    marginTop: 12,
  },
  expandedDivider: {
    height: 1,
    backgroundColor: colors.light.border,
    marginBottom: 12,
  },
  priceGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 12,
  },
  priceItem: {
    backgroundColor: colors.light.background,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  priceItemLabel: {
    fontSize: 10,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
    marginBottom: 2,
  },
  priceItemValue: {
    fontSize: 13,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  consensusRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  consensusLabel: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
  },
  consensusValue: {
    fontSize: 14,
    fontFamily: "Inter_700Bold",
    color: colors.light.tint,
  },
  exitReasonRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 12,
  },
  exitReasonText: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
  },
  votesTitle: {
    fontSize: 13,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
    marginBottom: 8,
  },
  voteRow: {
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.light.border,
  },
  voteTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  voteLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flex: 1,
  },
  voteName: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.text,
  },
  voteRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  voteConfBar: {
    width: 40,
    height: 4,
    backgroundColor: colors.light.border,
    borderRadius: 2,
    overflow: "hidden",
  },
  voteConfFill: {
    height: 4,
    borderRadius: 2,
  },
  voteDir: {
    fontSize: 10,
    fontFamily: "Inter_600SemiBold",
    width: 44,
    textAlign: "right",
  },
  voteConf: {
    fontSize: 11,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
    width: 30,
    textAlign: "right",
  },
  voteReasoning: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
    lineHeight: 16,
    marginTop: 4,
    paddingLeft: 20,
  },
});

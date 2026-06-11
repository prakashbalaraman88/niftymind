import React, { useState, useCallback, useEffect, useMemo } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  RefreshControl,
  ActivityIndicator,
  Alert,
  ScrollView,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import * as Haptics from "expo-haptics";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  withRepeat,
  withSequence,
  FadeInDown,
  FadeIn,
  FadeOut,
  LinearTransition,
  Easing,
  LayoutAnimationConfig,
} from "react-native-reanimated";

import colors from "@/constants/colors";
import { AGENT_INFO } from "@/constants/agents";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { PnlText } from "@/components/PnlText";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { Confetti } from "@/components/Confetti";
import type { Trade, TradeDetail, AgentVote } from "@/types/api";

const C = colors.dark;

const PROFIT_COLOR = "#10F0A0";
const PROFIT_GLOW = "rgba(16,240,160,0.3)";
const PROFIT_BORDER = "rgba(16,240,160,0.12)";
const PROFIT_TINT = "rgba(16,240,160,0.04)";
const LOSS_COLOR = "#FF3B5C";
const LOSS_GLOW = "rgba(255,59,92,0.3)";
const LOSS_BORDER = "rgba(255,59,92,0.12)";
const LOSS_TINT = "rgba(255,59,92,0.04)";
const OPEN_COLOR = "#8B5CF6";

function formatTradeTime(ts: string | null | undefined): string {
  if (!ts) return "--";
  try {
    const d = new Date(ts);
    return d.toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
      timeZone: "Asia/Kolkata",
    });
  } catch {
    return "--";
  }
}

function isToday(ts: string | null | undefined): boolean {
  if (!ts) return false;
  try {
    const d = new Date(ts);
    const now = new Date();
    return (
      d.getUTCFullYear() === now.getUTCFullYear() &&
      d.getUTCMonth() === now.getUTCMonth() &&
      d.getUTCDate() === now.getUTCDate()
    );
  } catch {
    return false;
  }
}

function fmtInr(n: number): string {
  const sign = n >= 0 ? "+" : "-";
  return `${sign}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

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

  const { data, isLoading, refetch, isRefetching, isError } = useQuery({
    queryKey: ["trades", filter],
    queryFn: () => api.getTrades(100, 0, filter === "all" ? undefined : filter),
    retry: 2,
    refetchInterval: 30_000,
    staleTime: 10_000,
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

  const stats = useMemo(() => {
    if (trades.length === 0) return null;
    const closed = trades.filter((t: Trade) => t.status === "CLOSED");
    const wins = closed.filter((t: Trade) => (t.pnl ?? 0) > 0).length;
    const winPct = closed.length > 0 ? (wins / closed.length) * 100 : 0;
    const todayPnl = closed
      .filter((t: Trade) => isToday(t.exit_time || t.updated_at))
      .reduce((sum: number, t: Trade) => sum + (t.pnl ?? 0), 0);
    return {
      total: trades.length,
      winPct,
      todayPnl,
    };
  }, [trades]);

  const handleFilterChange = useCallback((key: FilterStatus) => {
    Haptics.selectionAsync().catch(() => {});
    setFilter(key);
  }, []);

  const handleToggle = useCallback((id: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  const renderItem = useCallback(
    ({ item, index }: { item: Trade; index: number }) => (
      <TradeRow
        trade={item}
        index={index}
        isExpanded={expandedId === item.trade_id}
        onToggle={() => handleToggle(item.trade_id)}
      />
    ),
    [expandedId, handleToggle]
  );

  return (
    <>
      <Confetti active={showConfetti} onComplete={() => setShowConfetti(false)} />
      <View style={styles.container}>
        {stats && <PerformanceSummary stats={stats} />}

        <FilterBar filter={filter} onChange={handleFilterChange} />

        <LayoutAnimationConfig skipEntering>
          <FlatList
            data={trades}
            keyExtractor={(item) => item.trade_id}
            renderItem={renderItem}
            contentContainerStyle={styles.list}
            showsVerticalScrollIndicator={false}
            refreshControl={
              <RefreshControl
                refreshing={isRefetching}
                onRefresh={refetch}
                tintColor={C.accentBright}
              />
            }
            ListEmptyComponent={
              isLoading ? (
                <View style={styles.emptyWrap}>
                  <ActivityIndicator color={C.accentBright} />
                </View>
              ) : isError ? (
                <EmptyState
                  icon="alert-triangle"
                  title="Failed to load trades"
                  subtitle="Pull down to retry. Check your connection."
                />
              ) : (
                <EmptyState
                  icon="inbox"
                  title="No trades yet"
                  subtitle="Trades will appear here when the system executes orders."
                />
              )
            }
          />
        </LayoutAnimationConfig>
      </View>
    </>
  );
}

/* ──────────────────────────────────────────────────────────
   Performance Summary Bar
   ────────────────────────────────────────────────────────── */
function PerformanceSummary({
  stats,
}: {
  stats: { total: number; winPct: number; todayPnl: number };
}) {
  const pnlColor =
    stats.todayPnl > 0 ? PROFIT_COLOR : stats.todayPnl < 0 ? LOSS_COLOR : C.textSecondary;

  return (
    <Animated.View
      entering={FadeInDown.duration(400).springify().damping(18)}
      style={styles.summaryWrap}
    >
      <LinearGradient
        colors={["rgba(139,92,246,0.08)", "rgba(37,99,235,0.03)"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.summaryCard}
      >
        <View style={styles.summaryItem}>
          <Text style={styles.summaryLabel}>TRADES</Text>
          <Text style={styles.summaryValue}>{stats.total}</Text>
        </View>
        <View style={styles.summaryDivider} />
        <View style={styles.summaryItem}>
          <Text style={styles.summaryLabel}>WIN RATE</Text>
          <Text style={[styles.summaryValue, { color: C.accentBright }]}>
            {stats.winPct.toFixed(0)}%
          </Text>
        </View>
        <View style={styles.summaryDivider} />
        <View style={styles.summaryItem}>
          <Text style={styles.summaryLabel}>TODAY P&L</Text>
          <Text style={[styles.summaryValue, { color: pnlColor }]}>
            {fmtInr(stats.todayPnl)}
          </Text>
        </View>
      </LinearGradient>
    </Animated.View>
  );
}

/* ──────────────────────────────────────────────────────────
   Filter Bar with animated active indicator
   ────────────────────────────────────────────────────────── */
function FilterBar({
  filter,
  onChange,
}: {
  filter: FilterStatus;
  onChange: (key: FilterStatus) => void;
}) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.filterBar}
    >
      {FILTERS.map((f) => {
        const active = filter === f.key;
        return (
          <Pressable key={f.key} onPress={() => onChange(f.key)}>
            <Animated.View
              layout={LinearTransition.springify().damping(18)}
              style={styles.filterPillWrap}
            >
              {active ? (
                <LinearGradient
                  colors={C.gradient.accent}
                  start={{ x: 0, y: 0 }}
                  end={{ x: 1, y: 0 }}
                  style={styles.filterPillActive}
                >
                  <Text style={styles.filterTextActive}>{f.label}</Text>
                </LinearGradient>
              ) : (
                <View style={styles.filterPill}>
                  <Text style={styles.filterText}>{f.label}</Text>
                </View>
              )}
            </Animated.View>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

/* ──────────────────────────────────────────────────────────
   Trade Row
   ────────────────────────────────────────────────────────── */
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
  const dirVariant =
    trade.direction === "BULLISH" || trade.direction === "BUY" ? "bullish" : "bearish";
  const isOpen = trade.status === "OPEN";
  const isClosed = trade.status === "CLOSED";
  const displayPnl = isOpen ? trade.unrealized_pnl : trade.pnl;
  const isProfitable = (displayPnl ?? 0) > 0;
  const isLoss = (displayPnl ?? 0) < 0;

  const accentColor = isOpen
    ? OPEN_COLOR
    : trade.direction === "BULLISH" || trade.direction === "BUY"
    ? PROFIT_COLOR
    : LOSS_COLOR;

  const tintColor = isClosed
    ? isProfitable
      ? PROFIT_TINT
      : isLoss
      ? LOSS_TINT
      : "transparent"
    : "transparent";

  const borderColor = isClosed
    ? isProfitable
      ? PROFIT_BORDER
      : isLoss
      ? LOSS_BORDER
      : C.cardBorder
    : isOpen
    ? "rgba(139,92,246,0.18)"
    : C.cardBorder;

  const statusColor =
    trade.status === "OPEN"
      ? OPEN_COLOR
      : trade.status === "CLOSED"
      ? isProfitable
        ? PROFIT_COLOR
        : C.textSecondary
      : C.textTertiary;

  // Pulsing glow for open trades
  const glowAnim = useSharedValue(isOpen ? 0.3 : 0);
  useEffect(() => {
    if (isOpen) {
      glowAnim.value = withRepeat(
        withSequence(
          withTiming(1, { duration: 1400, easing: Easing.inOut(Easing.quad) }),
          withTiming(0.3, { duration: 1400, easing: Easing.inOut(Easing.quad) })
        ),
        -1,
        false
      );
    } else {
      glowAnim.value = withTiming(0, { duration: 300 });
    }
  }, [isOpen, glowAnim]);

  const pnlGlowStyle = useAnimatedStyle(() => ({
    opacity: glowAnim.value,
  }));

  // Chevron rotation
  const chevronRotate = useSharedValue(0);
  useEffect(() => {
    chevronRotate.value = withSpring(isExpanded ? 1 : 0, { damping: 16, stiffness: 180 });
  }, [isExpanded, chevronRotate]);

  const chevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${chevronRotate.value * 180}deg` }],
  }));

  // Press scale
  const pressScale = useSharedValue(1);
  const pressStyle = useAnimatedStyle(() => ({
    transform: [{ scale: pressScale.value }],
  }));

  const pnlColor = isProfitable ? PROFIT_COLOR : isLoss ? LOSS_COLOR : C.text;
  const pnlGlowColor = isProfitable ? PROFIT_GLOW : isLoss ? LOSS_GLOW : "transparent";

  return (
    <Animated.View
      entering={FadeInDown.delay(Math.min(index * 60, 600)).springify().damping(15)}
      layout={LinearTransition.springify().damping(18).mass(0.8)}
      style={[styles.cardOuter, pressStyle]}
    >
      <View style={[styles.card, { borderColor, backgroundColor: C.card }]}>
        {/* Background tint for profit/loss */}
        {tintColor !== "transparent" && (
          <View style={[StyleSheet.absoluteFill, { backgroundColor: tintColor }]} pointerEvents="none" />
        )}

        {/* Left accent bar */}
        <View style={[styles.accentBar, { backgroundColor: accentColor }]} />

        <Pressable
          onPress={onToggle}
          onPressIn={() => {
            pressScale.value = withSpring(0.985, { damping: 20, stiffness: 400 });
          }}
          onPressOut={() => {
            pressScale.value = withSpring(1, { damping: 18, stiffness: 300 });
          }}
          style={styles.cardInner}
        >
          <View style={styles.tradeHeader}>
            <View style={styles.tradeLeft}>
              <View style={styles.tradeSymbolRow}>
                <Text style={styles.tradeSymbol} numberOfLines={1}>
                  {trade.symbol}
                </Text>
                <StatusBadge label={trade.direction} variant={dirVariant} />
              </View>
              <Text style={styles.tradeMeta}>
                {trade.trade_type} · {trade.quantity} qty ·{" "}
                <Text style={{ color: statusColor, fontFamily: "Inter_600SemiBold" }}>
                  {trade.status}
                </Text>
              </Text>
              <View style={styles.tradeTimeRow}>
                <Feather name="clock" size={10} color={C.textTertiary} />
                <Text style={styles.tradeTime}>
                  {formatTradeTime(trade.entry_time || trade.created_at)}
                  {trade.exit_time ? `  →  ${formatTradeTime(trade.exit_time)}` : ""}
                </Text>
              </View>
            </View>

            <View style={styles.tradeRight}>
              {displayPnl != null ? (
                <View style={styles.pnlWrap}>
                  {pnlGlowColor !== "transparent" && (
                    <Animated.View
                      pointerEvents="none"
                      style={[
                        styles.pnlGlow,
                        { shadowColor: pnlColor, backgroundColor: pnlGlowColor },
                        isOpen ? pnlGlowStyle : { opacity: 0.6 },
                      ]}
                    />
                  )}
                  <PnlText
                    value={displayPnl}
                    prefix="₹"
                    style={{
                      fontSize: 16,
                      fontFamily: "Inter_700Bold",
                      color: pnlColor,
                      textShadowColor: pnlGlowColor,
                      textShadowOffset: { width: 0, height: 0 },
                      textShadowRadius: isOpen ? 8 : 6,
                    }}
                  />
                </View>
              ) : (
                <Text style={styles.tradePrice}>
                  ₹{trade.entry_price?.toLocaleString("en-IN")}
                </Text>
              )}
              {isOpen && (
                <View style={styles.liveBadge}>
                  <View style={styles.liveDot} />
                  <Text style={styles.liveText}>LIVE</Text>
                </View>
              )}
              <Animated.View style={chevronStyle}>
                <Feather name="chevron-down" size={16} color={C.textTertiary} />
              </Animated.View>
            </View>
          </View>

          {isExpanded && (
            <Animated.View
              entering={FadeIn.duration(220)}
              exiting={FadeOut.duration(150)}
              layout={LinearTransition.springify().damping(20)}
            >
              <TradeExpanded tradeId={trade.trade_id} trade={trade} />
            </Animated.View>
          )}
        </Pressable>
      </View>
    </Animated.View>
  );
}

/* ──────────────────────────────────────────────────────────
   Expanded Trade Detail
   ────────────────────────────────────────────────────────── */
function TradeExpanded({ tradeId, trade }: { tradeId: string; trade: Trade }) {
  const [closing, setClosing] = useState(false);
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery<TradeDetail>({
    queryKey: ["trade-detail", tradeId],
    queryFn: () => api.getTradeDetail(tradeId),
    retry: false,
  });

  const isOpen = trade.status === "OPEN";

  const handleClose = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    Alert.alert(
      "Close Position?",
      `Close ${trade.symbol} at market price?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Close",
          style: "destructive",
          onPress: async () => {
            setClosing(true);
            try {
              await api.closeTrade(tradeId);
              Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
              queryClient.invalidateQueries({ queryKey: ["trades"] });
            } catch (e: any) {
              setClosing(false);
              Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
              Alert.alert("Close failed", e.message || "Could not close position. Try again.");
            }
          },
        },
      ],
    );
  };

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

      {/* Price grid */}
      <View style={styles.priceGrid}>
        <PriceChip label="Entry" value={trade.entry_price} />
        <PriceChip label="SL" value={trade.sl_price} color={LOSS_COLOR} />
        <PriceChip label="Target" value={trade.target_price} color={PROFIT_COLOR} />
        {trade.exit_price != null && <PriceChip label="Exit" value={trade.exit_price} />}
        {isOpen && trade.current_price != null && (
          <PriceChip label="Current" value={trade.current_price} color={OPEN_COLOR} pulse />
        )}
      </View>

      {/* Consensus bar */}
      {trade.consensus_score != null && (
        <ConsensusBar score={trade.consensus_score} />
      )}

      {/* Exit reason */}
      {trade.exit_reason && (
        <View style={styles.exitReasonBadge}>
          <Feather name="log-out" size={11} color={C.textSecondary} />
          <Text style={styles.exitReasonText}>{trade.exit_reason}</Text>
        </View>
      )}

      {/* Close button */}
      {isOpen && (
        <Pressable onPress={handleClose} disabled={closing} style={{ marginTop: 14 }}>
          <LinearGradient
            colors={closing ? ["#444", "#333"] : ["#FF3B5C", "#FF6B81"]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 0 }}
            style={styles.closeBtn}
          >
            {closing ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <>
                <Feather name="x-circle" size={14} color="#fff" />
                <Text style={styles.closeBtnText}>Close Position</Text>
              </>
            )}
          </LinearGradient>
        </Pressable>
      )}

      {/* Agent votes */}
      {votes.length > 0 && (
        <View style={styles.votesSection}>
          <View style={styles.votesHeader}>
            <Feather name="users" size={12} color={C.textSecondary} />
            <Text style={styles.votesTitle}>AGENT VOTES</Text>
            <View style={styles.votesCount}>
              <Text style={styles.votesCountText}>{votes.length}</Text>
            </View>
          </View>
          <View style={styles.votesTable}>
            {votes.map((vote, idx) => (
              <VoteRow key={vote.agent_id} vote={vote} index={idx} />
            ))}
          </View>
        </View>
      )}
    </View>
  );
}

/* ──────────────────────────────────────────────────────────
   Price Chip
   ────────────────────────────────────────────────────────── */
function PriceChip({
  label,
  value,
  color,
  pulse = false,
}: {
  label: string;
  value?: number;
  color?: string;
  pulse?: boolean;
}) {
  const pulseAnim = useSharedValue(0);
  useEffect(() => {
    if (pulse) {
      pulseAnim.value = withRepeat(
        withSequence(
          withTiming(1, { duration: 1000 }),
          withTiming(0, { duration: 1000 })
        ),
        -1,
        false
      );
    }
  }, [pulse, pulseAnim]);

  const pulseStyle = useAnimatedStyle(() => ({
    opacity: 0.4 + pulseAnim.value * 0.4,
  }));

  return (
    <Animated.View entering={FadeIn.duration(200)} style={styles.priceChip}>
      {pulse && color && (
        <Animated.View
          pointerEvents="none"
          style={[
            StyleSheet.absoluteFill,
            { backgroundColor: color, borderRadius: 10 },
            pulseStyle,
            { opacity: 0.08 },
          ]}
        />
      )}
      <Text style={styles.priceChipLabel}>{label}</Text>
      <Text style={[styles.priceChipValue, color ? { color } : null]}>
        ₹{value?.toLocaleString("en-IN") ?? "--"}
      </Text>
    </Animated.View>
  );
}

/* ──────────────────────────────────────────────────────────
   Consensus Bar
   ────────────────────────────────────────────────────────── */
function ConsensusBar({ score }: { score: number }) {
  const progress = useSharedValue(0);
  useEffect(() => {
    progress.value = withTiming(score, {
      duration: 900,
      easing: Easing.out(Easing.cubic),
    });
  }, [score, progress]);

  const fillStyle = useAnimatedStyle(() => ({
    width: `${progress.value * 100}%`,
  }));

  return (
    <View style={styles.consensusRow}>
      <Text style={styles.consensusLabel}>Consensus</Text>
      <View style={styles.consensusBarOuter}>
        <Animated.View style={[styles.consensusBarFill, fillStyle]}>
          <LinearGradient
            colors={C.gradient.accent}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 0 }}
            style={StyleSheet.absoluteFill}
          />
        </Animated.View>
      </View>
      <Text style={styles.consensusValue}>{(score * 100).toFixed(0)}%</Text>
    </View>
  );
}

/* ──────────────────────────────────────────────────────────
   Vote Row
   ────────────────────────────────────────────────────────── */
function VoteRow({ vote, index }: { vote: AgentVote; index: number }) {
  const info = AGENT_INFO[vote.agent_id];
  const dirColor =
    vote.direction === "BULLISH"
      ? PROFIT_COLOR
      : vote.direction === "BEARISH"
      ? LOSS_COLOR
      : C.textSecondary;

  const confProgress = useSharedValue(0);
  useEffect(() => {
    confProgress.value = withTiming(vote.confidence, {
      duration: 600,
      easing: Easing.out(Easing.cubic),
    });
  }, [vote.confidence, confProgress]);

  const confStyle = useAnimatedStyle(() => ({
    width: `${confProgress.value * 100}%`,
  }));

  return (
    <Animated.View
      entering={FadeInDown.delay(index * 40).duration(280)}
      style={styles.voteRow}
    >
      <View style={styles.voteTop}>
        <View style={styles.voteLeft}>
          <View style={[styles.voteIconWrap, { backgroundColor: `${dirColor}18` }]}>
            <Feather name={info?.icon ?? "cpu"} size={11} color={dirColor} />
          </View>
          <Text style={styles.voteName} numberOfLines={1}>
            {info?.name || vote.agent_id}
          </Text>
        </View>
        <View style={styles.voteRight}>
          <View style={styles.voteConfBar}>
            <Animated.View
              style={[styles.voteConfFill, { backgroundColor: dirColor }, confStyle]}
            />
          </View>
          <Text style={[styles.voteDir, { color: dirColor }]}>
            {vote.direction?.substring(0, 4)}
          </Text>
          <Text style={styles.voteConf}>{(vote.confidence * 100).toFixed(0)}%</Text>
        </View>
      </View>
      {!!vote.reasoning && (
        <Text style={styles.voteReasoning} numberOfLines={3}>
          {vote.reasoning}
        </Text>
      )}
    </Animated.View>
  );
}

/* ──────────────────────────────────────────────────────────
   Styles
   ────────────────────────────────────────────────────────── */
const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },

  emptyWrap: { marginTop: 60, alignItems: "center" },

  /* Summary */
  summaryWrap: { paddingHorizontal: 20, paddingTop: 12 },
  summaryCard: {
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 14,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderWidth: 1,
    borderColor: "rgba(139,92,246,0.12)",
    overflow: "hidden",
  },
  summaryItem: { flex: 1, alignItems: "center" },
  summaryLabel: {
    fontSize: 9,
    fontFamily: "Inter_600SemiBold",
    color: C.textTertiary,
    letterSpacing: 1.2,
    marginBottom: 4,
  },
  summaryValue: {
    fontSize: 16,
    fontFamily: "Inter_700Bold",
    color: C.text,
  },
  summaryDivider: {
    width: 1,
    height: 28,
    backgroundColor: C.separator,
    marginHorizontal: 8,
  },

  /* Filter */
  filterBar: {
    paddingHorizontal: 20,
    paddingVertical: 12,
    gap: 8,
    alignItems: "center",
  },
  filterPillWrap: {},
  filterPill: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 22,
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: C.cardBorder,
  },
  filterPillActive: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 22,
    shadowColor: C.accentBright,
    shadowOpacity: 0.4,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  filterText: {
    fontSize: 13,
    fontFamily: "Inter_500Medium",
    color: C.textSecondary,
  },
  filterTextActive: {
    fontSize: 13,
    fontFamily: "Inter_600SemiBold",
    color: "#fff",
  },

  /* List */
  list: { paddingHorizontal: 20, paddingBottom: 120, paddingTop: 4 },

  /* Card */
  cardOuter: { marginBottom: 10 },
  card: {
    borderRadius: 14,
    borderWidth: 1,
    overflow: "hidden",
    position: "relative",
  },
  accentBar: {
    position: "absolute",
    left: 0,
    top: 0,
    bottom: 0,
    width: 3,
    borderTopLeftRadius: 14,
    borderBottomLeftRadius: 14,
  },
  cardInner: { padding: 14, paddingLeft: 17 },
  tradeHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  tradeLeft: { flex: 1, marginRight: 12 },
  tradeSymbolRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 4,
  },
  tradeSymbol: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: C.text,
    flexShrink: 1,
  },
  tradeMeta: {
    fontSize: 12,
    fontFamily: "Inter_400Regular",
    color: C.textSecondary,
  },
  tradeTimeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    marginTop: 4,
  },
  tradeTime: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: C.textTertiary,
  },
  tradeRight: { alignItems: "flex-end", gap: 4 },
  pnlWrap: { position: "relative", paddingHorizontal: 4 },
  pnlGlow: {
    position: "absolute",
    top: -4,
    left: -4,
    right: -4,
    bottom: -4,
    borderRadius: 8,
    shadowOpacity: 0.6,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 0 },
  },
  tradePnl: {
    fontSize: 16,
    fontFamily: "Inter_700Bold",
  },
  tradePrice: {
    fontSize: 14,
    fontFamily: "Inter_600SemiBold",
    color: C.text,
  },
  liveBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "rgba(139,92,246,0.12)",
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 6,
  },
  liveDot: {
    width: 5,
    height: 5,
    borderRadius: 3,
    backgroundColor: OPEN_COLOR,
  },
  liveText: {
    fontSize: 9,
    fontFamily: "Inter_700Bold",
    color: OPEN_COLOR,
    letterSpacing: 1,
  },

  /* Expanded */
  expandedLoading: { paddingVertical: 16, alignItems: "center" },
  expanded: { marginTop: 14 },
  expandedDivider: {
    height: 1,
    backgroundColor: C.separator,
    marginBottom: 14,
  },

  /* Price chips */
  priceGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 14,
  },
  priceChip: {
    backgroundColor: C.elevated,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.04)",
    minWidth: 72,
    overflow: "hidden",
  },
  priceChipLabel: {
    fontSize: 9,
    fontFamily: "Inter_600SemiBold",
    color: C.textTertiary,
    marginBottom: 3,
    letterSpacing: 0.8,
  },
  priceChipValue: {
    fontSize: 13,
    fontFamily: "Inter_700Bold",
    color: C.text,
  },

  /* Consensus */
  consensusRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: 12,
  },
  consensusLabel: {
    fontSize: 11,
    fontFamily: "Inter_600SemiBold",
    color: C.textSecondary,
    width: 72,
    letterSpacing: 0.3,
  },
  consensusBarOuter: {
    flex: 1,
    height: 6,
    backgroundColor: C.elevated,
    borderRadius: 3,
    overflow: "hidden",
  },
  consensusBarFill: {
    height: 6,
    borderRadius: 3,
    overflow: "hidden",
  },
  consensusValue: {
    fontSize: 12,
    fontFamily: "Inter_700Bold",
    color: C.accentBright,
    width: 40,
    textAlign: "right",
  },

  /* Exit reason */
  exitReasonBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: C.elevated,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    alignSelf: "flex-start",
    marginBottom: 4,
  },
  exitReasonText: {
    fontSize: 11,
    fontFamily: "Inter_500Medium",
    color: C.textSecondary,
  },

  /* Close button */
  closeBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderRadius: 12,
    paddingVertical: 12,
    shadowColor: LOSS_COLOR,
    shadowOpacity: 0.4,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 5,
  },
  closeBtnText: {
    fontSize: 13,
    fontFamily: "Inter_700Bold",
    color: "#fff",
    letterSpacing: 0.3,
  },

  /* Votes */
  votesSection: { marginTop: 16 },
  votesHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 10,
  },
  votesTitle: {
    fontSize: 10,
    fontFamily: "Inter_700Bold",
    color: C.textSecondary,
    letterSpacing: 1.2,
  },
  votesCount: {
    backgroundColor: C.elevated,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 5,
    marginLeft: 2,
  },
  votesCountText: {
    fontSize: 9,
    fontFamily: "Inter_700Bold",
    color: C.textTertiary,
  },
  votesTable: {
    backgroundColor: "rgba(255,255,255,0.015)",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.03)",
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  voteRow: {
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(255,255,255,0.03)",
  },
  voteTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  voteLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
    flex: 1,
  },
  voteIconWrap: {
    width: 22,
    height: 22,
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
  },
  voteName: {
    fontSize: 12,
    fontFamily: "Inter_600SemiBold",
    color: C.text,
    flexShrink: 1,
  },
  voteRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  voteConfBar: {
    width: 48,
    height: 4,
    backgroundColor: C.elevated,
    borderRadius: 2,
    overflow: "hidden",
  },
  voteConfFill: {
    height: 4,
    borderRadius: 2,
  },
  voteDir: {
    fontSize: 10,
    fontFamily: "Inter_700Bold",
    width: 32,
    textAlign: "right",
    letterSpacing: 0.3,
  },
  voteConf: {
    fontSize: 11,
    fontFamily: "Inter_600SemiBold",
    color: C.textSecondary,
    width: 30,
    textAlign: "right",
  },
  voteReasoning: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: C.textTertiary,
    lineHeight: 16,
    marginTop: 5,
    paddingLeft: 29,
  },
});

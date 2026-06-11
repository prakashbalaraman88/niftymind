import React, { useEffect, useRef, useState } from "react";
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
  withDelay,
  interpolate,
  interpolateColor,
  Easing,
  FadeInDown,
  FadeIn,
  ZoomIn,
} from "react-native-reanimated";
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
import { EquityWidget } from "@/components/EquityWidget";
import type { DashboardData, TickData } from "@/types/api";

const C = colors.dark;

const AnimatedLinearGradient = Animated.createAnimatedComponent(LinearGradient);

export default function DashboardScreen() {
  const insets = useSafeAreaInsets();
  const { connected, ticks, subscribe } = useWebSocket();
  const queryClient = useQueryClient();
  const [showConfetti, setShowConfetti] = useState(false);
  const prevPnlRef = useRef<number>(0);

  // Reanimated values for header
  const titleShimmer = useSharedValue(0);
  const liveDotScale = useSharedValue(1);
  const liveDotOpacity = useSharedValue(1);
  const heroBgPulse = useSharedValue(0);

  const { data, isLoading, isError, refetch, isRefetching } = useQuery<DashboardData>({
    queryKey: ["dashboard"],
    queryFn: api.getDashboard,
    refetchInterval: 30000,
    retry: false,
  });

  useEffect(() => {
    // Title shimmer loop
    titleShimmer.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 2200, easing: Easing.inOut(Easing.ease) }),
        withTiming(0, { duration: 2200, easing: Easing.inOut(Easing.ease) })
      ),
      -1,
      false
    );
    // Hero background pulse
    heroBgPulse.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 2800, easing: Easing.inOut(Easing.ease) }),
        withTiming(0, { duration: 2800, easing: Easing.inOut(Easing.ease) })
      ),
      -1,
      false
    );
  }, []);

  useEffect(() => {
    if (connected) {
      liveDotScale.value = withRepeat(
        withSequence(
          withTiming(1.6, { duration: 800, easing: Easing.out(Easing.ease) }),
          withTiming(1, { duration: 800, easing: Easing.in(Easing.ease) })
        ),
        -1,
        false
      );
      liveDotOpacity.value = withRepeat(
        withSequence(
          withTiming(0.6, { duration: 800 }),
          withTiming(1, { duration: 800 })
        ),
        -1,
        false
      );
    } else {
      liveDotScale.value = withTiming(1);
      liveDotOpacity.value = withTiming(1);
    }
  }, [connected]);

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
  const dailyPnl = data?.executor?.daily_pnl ?? data?.executor?.today_pnl ?? 0;
  const unrealizedPnl = data?.positions?.tracker?.total_unrealized_pnl ?? 0;
  const totalPnl = dailyPnl + unrealizedPnl;
  const openPositions = data?.positions?.open || [];
  const capital = data?.capital ?? 500000;
  const vixHalt = data?.risk_limits?.vix_halt_threshold ?? 25;
  const vixValue = vixTick?.ltp ?? 0;
  const vixBreached = vixValue > 0 && vixValue > vixHalt;
  const totalTrades = data?.executor?.total_trades ?? 0;
  const pnlPct = capital > 0 ? (totalPnl / capital) * 100 : 0;
  const isProfit = totalPnl >= 0;

  useEffect(() => {
    if (totalPnl > 0 && prevPnlRef.current <= 0 && !isLoading) {
      setShowConfetti(true);
    }
    prevPnlRef.current = totalPnl;
  }, [totalPnl, isLoading]);

  // Animated styles
  const titleShimmerStyle = useAnimatedStyle(() => ({
    opacity: interpolate(titleShimmer.value, [0, 0.5, 1], [0.88, 1, 0.88]),
    textShadowRadius: interpolate(titleShimmer.value, [0, 0.5, 1], [8, 22, 8]),
  }));

  const liveDotStyle = useAnimatedStyle(() => ({
    transform: [{ scale: liveDotScale.value }],
    opacity: liveDotOpacity.value,
  }));

  const liveDotHaloStyle = useAnimatedStyle(() => ({
    opacity: interpolate(liveDotScale.value, [1, 1.6], [0, 0.5]),
    transform: [{ scale: interpolate(liveDotScale.value, [1, 1.6], [1, 2.4]) }],
  }));

  const heroPulseStyle = useAnimatedStyle(() => ({
    opacity: interpolate(heroBgPulse.value, [0, 1], [0.4, 0.85]),
    transform: [{ scale: interpolate(heroBgPulse.value, [0, 1], [1, 1.08]) }],
  }));

  const heroGlowColor = isProfit ? "rgba(16,240,160,0.18)" : "rgba(255,59,92,0.18)";
  const heroBorderColor = isProfit ? "rgba(16,240,160,0.22)" : "rgba(255,59,92,0.22)";

  return (
    <>
      <Confetti active={showConfetti} onComplete={() => setShowConfetti(false)} />
      <ScrollView
        style={styles.container}
        contentContainerStyle={{ paddingTop: insets.top + 16, paddingBottom: 100 }}
        refreshControl={
          <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={C.accentBright} />
        }
        showsVerticalScrollIndicator={false}
      >
        {/* HEADER */}
        <Animated.View
          entering={FadeInDown.duration(600).springify().damping(16)}
          style={styles.header}
        >
          <View>
            <Animated.Text
              style={[
                styles.appTitle,
                titleShimmerStyle,
                { textShadowColor: C.accentGlow, textShadowOffset: { width: 0, height: 0 } },
              ]}
            >
              NiftyMind
            </Animated.Text>
            <View style={styles.statusRow}>
              <View style={styles.liveDotWrap}>
                <Animated.View
                  style={[
                    styles.liveDotHalo,
                    { backgroundColor: connected ? C.green : C.red },
                    liveDotHaloStyle,
                  ]}
                />
                <Animated.View
                  style={[
                    styles.liveDot,
                    {
                      backgroundColor: connected ? C.green : C.red,
                      shadowColor: connected ? C.green : C.red,
                    },
                    liveDotStyle,
                  ]}
                />
              </View>
              <Text style={styles.statusText}>{connected ? "Live" : "Offline"}</Text>
              <View style={styles.frostedBadge}>
                <StatusBadge label={tradingMode} variant={tradingMode === "live" ? "live" : "paper"} />
              </View>
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
            {/* P&L HERO */}
            <Animated.View
              entering={FadeInDown.delay(100).duration(700).springify().damping(14)}
              style={[styles.pnlHeroWrap, { shadowColor: isProfit ? C.green : C.red }]}
            >
              <LinearGradient
                colors={
                  isProfit
                    ? ["rgba(16,240,160,0.14)", "rgba(16,240,160,0.02)", "rgba(22,24,30,0.0)"]
                    : ["rgba(255,59,92,0.14)", "rgba(255,59,92,0.02)", "rgba(22,24,30,0.0)"]
                }
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 1 }}
                style={[styles.pnlHero, { borderColor: heroBorderColor }]}
              >
                {/* Subtle pulsing radial glow */}
                <Animated.View
                  pointerEvents="none"
                  style={[
                    styles.heroGlowOrb,
                    { backgroundColor: heroGlowColor },
                    heroPulseStyle,
                  ]}
                />

                <View style={styles.pnlLabelRow}>
                  <View style={[styles.pnlLabelDot, { backgroundColor: isProfit ? C.green : C.red }]} />
                  <Text style={styles.pnlLabel}>TODAY'S P&L</Text>
                </View>

                <AnimatedNumber
                  value={totalPnl}
                  prefix="₹"
                  style={[
                    styles.pnlHeroValue,
                    {
                      color: totalPnl > 0 ? C.green : totalPnl < 0 ? C.red : C.textSecondary,
                      textShadowColor: totalPnl > 0 ? C.greenGlow : totalPnl < 0 ? C.redGlow : "transparent",
                      textShadowOffset: { width: 0, height: 0 },
                      textShadowRadius: 24,
                    },
                  ] as any}
                  formatFn={(v) => {
                    const sign = v > 0 ? "+" : "";
                    return `₹${sign}${Math.round(v).toLocaleString("en-IN")}`;
                  }}
                />

                {pnlPct !== 0 && (
                  <Animated.View
                    entering={ZoomIn.delay(500).duration(400).springify()}
                    style={[
                      styles.pnlPctBadge,
                      {
                        backgroundColor: isProfit ? C.greenDark : C.redDark,
                        borderColor: isProfit ? "rgba(16,240,160,0.3)" : "rgba(255,59,92,0.3)",
                        shadowColor: isProfit ? C.green : C.red,
                      },
                    ]}
                  >
                    <Feather
                      name={isProfit ? "trending-up" : "trending-down"}
                      size={12}
                      color={isProfit ? C.green : C.red}
                    />
                    <Text style={[styles.pnlPctText, { color: isProfit ? C.green : C.red }]}>
                      {isProfit ? "+" : ""}
                      {pnlPct.toFixed(2)}% return
                    </Text>
                  </Animated.View>
                )}

                <View style={styles.pnlMeta}>
                  <PnlMetaItem label="Capital" value={`₹${(capital / 1000).toFixed(0)}K`} delay={650} />
                  <View style={styles.pnlMetaDivider} />
                  <PnlMetaItem label="Open" value={String(openPositions.length)} delay={720} />
                  <View style={styles.pnlMetaDivider} />
                  <PnlMetaItem label="Trades" value={String(totalTrades)} delay={790} />
                </View>
              </LinearGradient>
            </Animated.View>

            {/* MARKET PRICES */}
            <Animated.View
              entering={FadeInDown.delay(220).duration(600).springify()}
              style={styles.priceRow}
            >
              <PriceCard label="NIFTY 50" tick={niftyTick} />
              <PriceCard label="BANKNIFTY" tick={bankNiftyTick} />
            </Animated.View>

            {/* VIX */}
            <Animated.View entering={FadeInDown.delay(300).duration(600).springify()}>
              <LinearGradient
                colors={
                  vixBreached
                    ? ["rgba(255,59,92,0.08)", "rgba(26,28,36,0.95)"]
                    : ["rgba(255,255,255,0.03)", "rgba(26,28,36,0.95)"]
                }
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 1 }}
                style={styles.vixCard}
              >
                <View style={styles.vixRow}>
                  <View style={styles.vixLeft}>
                    <View
                      style={[
                        styles.vixIcon,
                        {
                          backgroundColor: vixBreached ? C.redDark : C.greenDark,
                          shadowColor: vixBreached ? C.red : C.green,
                        },
                      ]}
                    >
                      <Feather
                        name="activity"
                        size={15}
                        color={vixBreached ? C.red : C.green}
                      />
                    </View>
                    <View>
                      <Text style={styles.vixLabel}>India VIX</Text>
                      <Text style={styles.vixSublabel}>Volatility Index</Text>
                    </View>
                  </View>
                  <View style={styles.vixRight}>
                    <Text
                      style={[
                        styles.vixValue,
                        {
                          color: vixBreached ? C.red : C.text,
                          textShadowColor: vixBreached ? C.redGlow : "transparent",
                          textShadowRadius: 10,
                          textShadowOffset: { width: 0, height: 0 },
                        },
                      ]}
                    >
                      {vixValue > 0 ? vixValue.toFixed(2) : "--"}
                    </Text>
                    <StatusBadge
                      label={vixBreached ? "HALT" : vixValue > 0 ? "OK" : "N/A"}
                      variant={vixBreached ? "high" : "low"}
                    />
                  </View>
                </View>
                {vixValue > 0 && (
                  <VixBar vixValue={vixValue} vixHalt={vixHalt} breached={vixBreached} />
                )}
              </LinearGradient>
            </Animated.View>

            <EquityWidget />

            {/* AGENT GRID HEADER */}
            <Animated.View
              entering={FadeInDown.delay(380).duration(500).springify()}
              style={styles.sectionHeader}
            >
              <View style={styles.sectionHeaderLeft}>
                <Text style={styles.sectionTitle}>Agent Grid</Text>
                <Text style={styles.sectionSubtitle}>Live AI signals</Text>
              </View>
              <View style={styles.sectionBadge}>
                <View style={styles.sectionBadgeDot} />
                <Text style={styles.sectionBadgeText}>12 AI</Text>
              </View>
            </Animated.View>

            <View style={styles.agentGrid}>
              {AGENT_IDS.map((id, i) => (
                <AgentCell key={id} agentId={id} index={i} />
              ))}
            </View>

            {/* OPEN POSITIONS */}
            {openPositions.length > 0 && (
              <>
                <Animated.View
                  entering={FadeInDown.duration(500).springify()}
                  style={styles.sectionHeader}
                >
                  <View style={styles.sectionHeaderLeft}>
                    <Text style={styles.sectionTitle}>Open Positions</Text>
                    <Text style={styles.sectionSubtitle}>Live unrealized P&L</Text>
                  </View>
                  <View style={styles.countBadge}>
                    <Text style={styles.countBadgeText}>{openPositions.length}</Text>
                    <Text style={styles.countBadgeLabel}>active</Text>
                  </View>
                </Animated.View>
                {openPositions.map((pos, i) => (
                  <Animated.View
                    key={pos.trade_id}
                    entering={FadeInDown.delay(i * 60).duration(450).springify()}
                  >
                    <PositionRow pos={pos} />
                  </Animated.View>
                ))}
              </>
            )}
          </>
        )}
      </ScrollView>
    </>
  );
}

/* ───────────────────────── Sub-components ───────────────────────── */

function PnlMetaItem({
  label,
  value,
  delay = 0,
}: {
  label: string;
  value: string;
  delay?: number;
}) {
  return (
    <Animated.View
      entering={FadeIn.delay(delay).duration(500)}
      style={styles.pnlMetaItem}
    >
      <Text style={styles.pnlMetaLabel}>{label}</Text>
      <Text style={styles.pnlMetaValue}>{value}</Text>
    </Animated.View>
  );
}

function VixBar({
  vixValue,
  vixHalt,
  breached,
}: {
  vixValue: number;
  vixHalt: number;
  breached: boolean;
}) {
  const progress = useSharedValue(0);

  useEffect(() => {
    const target = Math.min((vixValue / (vixHalt * 1.5)) * 100, 100);
    progress.value = withDelay(
      400,
      withTiming(target, { duration: 900, easing: Easing.out(Easing.cubic) })
    );
  }, [vixValue, vixHalt]);

  const barStyle = useAnimatedStyle(() => ({
    width: `${progress.value}%`,
  }));

  return (
    <View style={styles.vixBarSection}>
      <View style={styles.vixBarLabels}>
        <Text style={styles.vixThresholdText}>0</Text>
        <Text style={styles.vixThresholdText}>Halt at {vixHalt}</Text>
      </View>
      <View style={styles.vixBarOuter}>
        <Animated.View style={[styles.vixBarInner, barStyle]}>
          <LinearGradient
            colors={
              breached ? [C.red, "#FF6B81"] : [C.green, "#22D47A"]
            }
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 0 }}
            style={styles.vixBarFill}
          />
        </Animated.View>
        <View
          style={[
            styles.vixThresholdMark,
            { left: `${(vixHalt / (vixHalt * 1.5)) * 100}%` },
          ]}
        />
      </View>
    </View>
  );
}

function PriceCard({ label, tick }: { label: string; tick?: TickData }) {
  const price = tick?.ltp ?? 0;
  const change = tick?.change_pct ?? 0;
  const isUp = change >= 0;

  const scale = useSharedValue(1);
  const flash = useSharedValue(0);
  const prevPrice = useRef(price);

  useEffect(() => {
    if (prevPrice.current !== price && price > 0) {
      const wentUp = price > prevPrice.current;
      prevPrice.current = price;
      scale.value = withSequence(
        withTiming(1.06, { duration: 120, easing: Easing.out(Easing.ease) }),
        withSpring(1, { damping: 10, stiffness: 180 })
      );
      flash.value = wentUp ? 1 : -1;
      flash.value = withSequence(
        withTiming(wentUp ? 1 : -1, { duration: 130 }),
        withTiming(0, { duration: 520, easing: Easing.out(Easing.ease) })
      );
    }
  }, [price]);

  const priceTextStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
    color: interpolateColor(
      flash.value,
      [-1, 0, 1],
      [C.red, C.text, C.green]
    ),
  }));

  const flashBgStyle = useAnimatedStyle(() => ({
    backgroundColor: interpolateColor(
      flash.value,
      [-1, 0, 1],
      ["rgba(255,59,92,0.18)", "rgba(255,255,255,0)", "rgba(16,240,160,0.18)"]
    ),
  }));

  return (
    <View style={styles.priceCardWrap}>
      <LinearGradient
        colors={["rgba(255,255,255,0.04)", "rgba(26,28,36,0.9)"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 0, y: 1 }}
        style={styles.priceCard}
      >
        <Animated.View style={[StyleSheet.absoluteFill, flashBgStyle, { borderRadius: 18 }]} />
        <View style={styles.priceHeader}>
          <Text style={styles.priceLabel}>{label}</Text>
          {price > 0 && (
            <View
              style={[
                styles.priceDot,
                { backgroundColor: isUp ? C.green : C.red, shadowColor: isUp ? C.green : C.red },
              ]}
            />
          )}
        </View>
        <Animated.Text style={[styles.priceValue, priceTextStyle]}>
          {price > 0 ? price.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : "--"}
        </Animated.Text>
        {price > 0 && (
          <View
            style={[
              styles.priceChangeRow,
              {
                backgroundColor: isUp ? C.greenDark : C.redDark,
                borderColor: isUp ? "rgba(16,240,160,0.25)" : "rgba(255,59,92,0.25)",
              },
            ]}
          >
            <Feather
              name={isUp ? "arrow-up-right" : "arrow-down-right"}
              size={11}
              color={isUp ? C.green : C.red}
            />
            <Text style={[styles.priceChangeText, { color: isUp ? C.green : C.red }]}>
              {Math.abs(change).toFixed(2)}%
            </Text>
          </View>
        )}
      </LinearGradient>
    </View>
  );
}

function AgentCell({ agentId, index }: { agentId: string; index: number }) {
  const info = AGENT_INFO[agentId];
  const { subscribe } = useWebSocket();
  const [signal, setSignal] = useState<string>("--");
  const [active, setActive] = useState(false);

  const dotScale = useSharedValue(1);
  const dotOpacity = useSharedValue(1);

  useEffect(() => {
    if (active) {
      dotScale.value = withRepeat(
        withSequence(
          withTiming(1.7, { duration: 700, easing: Easing.out(Easing.ease) }),
          withTiming(1, { duration: 700, easing: Easing.in(Easing.ease) })
        ),
        -1,
        false
      );
      dotOpacity.value = withRepeat(
        withSequence(
          withTiming(0.55, { duration: 700 }),
          withTiming(1, { duration: 700 })
        ),
        -1,
        false
      );
    } else {
      dotScale.value = withTiming(1);
      dotOpacity.value = withTiming(1);
    }
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
    return () => {
      u1();
      u2();
    };
  }, [agentId, subscribe]);

  const dirColor =
    signal === "BULLISH" ? C.green : signal === "BEARISH" ? C.red : C.textTertiary;

  const dotStyle = useAnimatedStyle(() => ({
    transform: [{ scale: dotScale.value }],
    opacity: dotOpacity.value,
  }));

  return (
    <Animated.View
      entering={FadeInDown.delay(index * 40)
        .duration(450)
        .springify()
        .damping(14)}
      style={[
        styles.agentCell,
        active && { borderColor: "rgba(139,92,246,0.25)" },
      ]}
    >
      <LinearGradient
        colors={
          active
            ? ["rgba(139,92,246,0.08)", "rgba(26,28,36,0.95)"]
            : ["rgba(255,255,255,0.03)", "rgba(26,28,36,0.9)"]
        }
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.agentCellInner}
      >
        <Animated.View
          style={[
            styles.agentActiveDot,
            {
              backgroundColor: active ? dirColor : C.textQuaternary,
              shadowColor: active ? dirColor : "transparent",
            },
            dotStyle,
          ]}
        />
        <View
          style={[
            styles.agentIconWrap,
            {
              backgroundColor: active ? `${dirColor}18` : "rgba(255,255,255,0.04)",
            },
          ]}
        >
          <Feather
            name={info?.icon ?? "cpu"}
            size={15}
            color={active ? dirColor : C.textTertiary}
          />
        </View>
        <Text style={styles.agentName} numberOfLines={1}>
          {info?.shortName || agentId}
        </Text>
        <Text
          style={[
            styles.agentSignal,
            { color: dirColor, opacity: signal === "--" ? 0.4 : 1 },
          ]}
          numberOfLines={1}
        >
          {signal === "--" ? "IDLE" : signal.substring(0, 4)}
        </Text>
      </LinearGradient>
    </Animated.View>
  );
}

function PositionRow({ pos }: { pos: any }) {
  const isBullish = pos.direction === "BULLISH" || pos.direction === "LONG" || pos.direction === "BUY";
  const barColor = isBullish ? C.green : C.red;

  return (
    <View style={styles.positionCardWrap}>
      <View style={[styles.positionBar, { backgroundColor: barColor, shadowColor: barColor }]} />
      <LinearGradient
        colors={["rgba(255,255,255,0.03)", "rgba(26,28,36,0.95)"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.positionCard}
      >
        <View style={styles.posRow}>
          <View style={styles.posLeft}>
            <View style={styles.posSymbolRow}>
              <Text style={styles.posSymbol}>{pos.symbol}</Text>
              <View
                style={[
                  styles.posDirBadge,
                  {
                    backgroundColor: isBullish ? C.greenDark : C.redDark,
                    borderColor: isBullish ? "rgba(16,240,160,0.25)" : "rgba(255,59,92,0.25)",
                  },
                ]}
              >
                <Feather
                  name={isBullish ? "trending-up" : "trending-down"}
                  size={10}
                  color={barColor}
                />
                <Text style={[styles.posDirText, { color: barColor }]}>
                  {pos.direction}
                </Text>
              </View>
            </View>
            <Text style={styles.posDetail}>
              {pos.quantity} qty · entry ₹{pos.entry_price?.toLocaleString("en-IN")}
            </Text>
          </View>
          <PnlText
            value={pos.unrealized_pnl ?? 0}
            prefix="₹"
            style={styles.posPnl}
            animate
          />
        </View>
      </LinearGradient>
    </View>
  );
}

/* ───────────────────────── Styles ───────────────────────── */

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },

  /* Header */
  header: { paddingHorizontal: 20, paddingBottom: 22 },
  appTitle: {
    fontSize: 34,
    fontFamily: "Inter_700Bold",
    color: C.text,
    letterSpacing: -1.2,
    textShadowRadius: 14,
  },
  statusRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 8 },
  liveDotWrap: {
    width: 10,
    height: 10,
    justifyContent: "center",
    alignItems: "center",
  },
  liveDotHalo: {
    position: "absolute",
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  liveDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 8,
    elevation: 6,
  },
  statusText: {
    fontSize: 13,
    fontFamily: "Inter_500Medium",
    color: C.textSecondary,
    letterSpacing: 0.2,
  },
  frostedBadge: {
    marginLeft: 4,
  },

  /* P&L Hero */
  pnlHeroWrap: {
    marginHorizontal: 20,
    marginBottom: 18,
    borderRadius: 26,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.35,
    shadowRadius: 24,
    elevation: 10,
  },
  pnlHero: {
    borderRadius: 26,
    padding: 24,
    borderWidth: 1,
    overflow: "hidden",
    backgroundColor: C.card,
  },
  heroGlowOrb: {
    position: "absolute",
    top: -120,
    right: -80,
    width: 260,
    height: 260,
    borderRadius: 130,
  },
  pnlLabelRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 10,
  },
  pnlLabelDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  pnlLabel: {
    fontSize: 11,
    fontFamily: "Inter_600SemiBold",
    color: C.textSecondary,
    letterSpacing: 1.8,
  },
  pnlHeroValue: {
    fontSize: 48,
    fontFamily: "Inter_700Bold",
    letterSpacing: -2,
    marginBottom: 10,
  },
  pnlPctBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 10,
    borderWidth: 1,
    marginBottom: 22,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.35,
    shadowRadius: 10,
    elevation: 4,
  },
  pnlPctText: {
    fontSize: 12,
    fontFamily: "Inter_600SemiBold",
    letterSpacing: 0.2,
  },
  pnlMeta: {
    flexDirection: "row",
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: "rgba(255,255,255,0.06)",
    paddingTop: 16,
  },
  pnlMetaItem: { flex: 1, alignItems: "center" },
  pnlMetaLabel: {
    fontSize: 10,
    fontFamily: "Inter_500Medium",
    color: C.textTertiary,
    marginBottom: 5,
    letterSpacing: 0.8,
  },
  pnlMetaValue: {
    fontSize: 17,
    fontFamily: "Inter_700Bold",
    color: C.text,
    letterSpacing: -0.3,
  },
  pnlMetaDivider: {
    width: 1,
    height: 30,
    backgroundColor: "rgba(255,255,255,0.08)",
  },

  /* Price Cards */
  priceRow: {
    flexDirection: "row",
    paddingHorizontal: 20,
    gap: 12,
    marginBottom: 14,
  },
  priceCardWrap: { flex: 1 },
  priceCard: {
    flex: 1,
    borderRadius: 18,
    padding: 14,
    borderWidth: 1,
    borderColor: C.cardBorder,
    overflow: "hidden",
  },
  priceHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  priceLabel: {
    fontSize: 10,
    fontFamily: "Inter_600SemiBold",
    color: C.textSecondary,
    letterSpacing: 1.2,
  },
  priceDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 6,
  },
  priceValue: {
    fontSize: 24,
    fontFamily: "Inter_700Bold",
    color: C.text,
    letterSpacing: -0.7,
  },
  priceChangeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    marginTop: 10,
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 7,
    borderWidth: 1,
    alignSelf: "flex-start",
  },
  priceChangeText: {
    fontSize: 11,
    fontFamily: "Inter_600SemiBold",
    letterSpacing: 0.2,
  },

  /* VIX */
  vixCard: {
    marginHorizontal: 20,
    marginBottom: 20,
    borderRadius: 20,
    padding: 16,
    borderWidth: 1,
    borderColor: C.cardBorder,
    overflow: "hidden",
  },
  vixRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  vixLeft: { flexDirection: "row", alignItems: "center", gap: 12 },
  vixIcon: {
    width: 38,
    height: 38,
    borderRadius: 12,
    justifyContent: "center",
    alignItems: "center",
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 8,
  },
  vixLabel: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: C.text,
    letterSpacing: -0.2,
  },
  vixSublabel: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: C.textTertiary,
    marginTop: 1,
  },
  vixRight: { flexDirection: "row", alignItems: "center", gap: 10 },
  vixValue: {
    fontSize: 24,
    fontFamily: "Inter_700Bold",
    letterSpacing: -0.6,
  },
  vixBarSection: { marginTop: 16 },
  vixBarLabels: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: 6,
  },
  vixThresholdText: {
    fontSize: 10,
    fontFamily: "Inter_500Medium",
    color: C.textTertiary,
    letterSpacing: 0.3,
  },
  vixBarOuter: {
    height: 6,
    backgroundColor: "rgba(255,255,255,0.05)",
    borderRadius: 3,
    overflow: "visible",
    position: "relative",
  },
  vixBarInner: {
    height: 6,
    borderRadius: 3,
    overflow: "hidden",
  },
  vixBarFill: {
    flex: 1,
    borderRadius: 3,
  },
  vixThresholdMark: {
    position: "absolute",
    top: -3,
    width: 2,
    height: 12,
    backgroundColor: C.red,
    borderRadius: 1,
    shadowColor: C.red,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 4,
  },

  /* Section headers */
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 20,
    marginTop: 4,
    marginBottom: 14,
  },
  sectionHeaderLeft: {},
  sectionTitle: {
    fontSize: 18,
    fontFamily: "Inter_700Bold",
    color: C.text,
    letterSpacing: -0.4,
  },
  sectionSubtitle: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: C.textTertiary,
    marginTop: 2,
    letterSpacing: 0.2,
  },
  sectionBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: C.accentLight,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderWidth: 1,
    borderColor: "rgba(139,92,246,0.2)",
  },
  sectionBadgeDot: {
    width: 5,
    height: 5,
    borderRadius: 3,
    backgroundColor: C.accentBright,
    shadowColor: C.accentBright,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 4,
  },
  sectionBadgeText: {
    fontSize: 11,
    fontFamily: "Inter_700Bold",
    color: C.accentBright,
    letterSpacing: 0.5,
  },
  sectionCount: {
    fontSize: 13,
    fontFamily: "Inter_500Medium",
    color: C.textSecondary,
  },
  countBadge: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 4,
    backgroundColor: "rgba(255,255,255,0.05)",
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderWidth: 1,
    borderColor: C.cardBorder,
  },
  countBadgeText: {
    fontSize: 13,
    fontFamily: "Inter_700Bold",
    color: C.text,
  },
  countBadgeLabel: {
    fontSize: 11,
    fontFamily: "Inter_500Medium",
    color: C.textTertiary,
  },

  /* Agent grid */
  agentGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    paddingHorizontal: 16,
    gap: 8,
    marginBottom: 22,
  },
  agentCell: {
    width: "22.7%",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: C.cardBorder,
    overflow: "hidden",
  },
  agentCellInner: {
    padding: 11,
    alignItems: "center",
    gap: 6,
    minHeight: 88,
    justifyContent: "center",
  },
  agentActiveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    position: "absolute",
    top: 8,
    right: 8,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 6,
  },
  agentIconWrap: {
    width: 28,
    height: 28,
    borderRadius: 10,
    justifyContent: "center",
    alignItems: "center",
    marginTop: 2,
  },
  agentName: {
    fontSize: 10,
    fontFamily: "Inter_600SemiBold",
    color: C.textSecondary,
    textAlign: "center",
    letterSpacing: 0.2,
  },
  agentSignal: {
    fontSize: 9,
    fontFamily: "Inter_700Bold",
    letterSpacing: 0.6,
  },

  /* Positions */
  positionCardWrap: {
    marginHorizontal: 20,
    marginBottom: 10,
    borderRadius: 16,
    flexDirection: "row",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: C.cardBorder,
  },
  positionBar: {
    width: 3,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 6,
  },
  positionCard: {
    flex: 1,
    padding: 14,
  },
  posRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  posLeft: { flex: 1 },
  posSymbolRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 4,
  },
  posSymbol: {
    fontSize: 15,
    fontFamily: "Inter_700Bold",
    color: C.text,
    letterSpacing: -0.2,
  },
  posDirBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
    borderWidth: 1,
  },
  posDirText: {
    fontSize: 9,
    fontFamily: "Inter_700Bold",
    letterSpacing: 0.4,
  },
  posDetail: {
    fontSize: 12,
    fontFamily: "Inter_400Regular",
    color: C.textSecondary,
  },
  posPnl: { fontSize: 16 },
});

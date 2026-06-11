import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, { FadeInDown } from 'react-native-reanimated';
import Svg, { Path, Defs, LinearGradient as SvgGradient, Stop } from 'react-native-svg';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import colors from '@/constants/colors';
import type { DailyPnlEntry } from '@/types/api';

const C = colors.dark;

export function EquityWidget() {
  const { data } = useQuery({
    queryKey: ['daily-pnl'],
    queryFn: api.getDailyPnl,
    refetchInterval: 60000,
    retry: false,
  });

  const daily = data?.daily?.slice(0, 30).reverse() ?? [];

  if (daily.length < 2) return null;

  const values = daily.map((d: DailyPnlEntry) => d.cumulative_pnl);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;
  const isProfit = values[values.length - 1] >= 0;

  // Build SVG path from values
  const W = 300, H = 56;
  const points = values.map((v: number, i: number) => {
    const x = (i / (values.length - 1)) * W;
    const y = H - ((v - minVal) / range) * H * 0.85 - H * 0.075;
    return `${x},${y}`;
  });
  const linePath = `M ${points.join(' L ')}`;
  const areaPath = `${linePath} L ${W},${H} L 0,${H} Z`;

  const latestPnl = values[values.length - 1];
  const todayPnl = daily[daily.length - 1]?.daily_pnl ?? 0;
  const totalDays = daily.filter((d: DailyPnlEntry) => d.daily_pnl !== 0).length;
  const winDays = daily.filter((d: DailyPnlEntry) => d.daily_pnl > 0).length;
  const winRate = totalDays > 0 ? Math.round((winDays / totalDays) * 100) : 0;

  const lineColor = isProfit ? C.green : C.red;

  return (
    <Animated.View entering={FadeInDown.delay(200).springify()} style={styles.container}>
      <LinearGradient
        colors={isProfit ? ['rgba(16,240,160,0.06)', 'transparent'] : ['rgba(255,59,92,0.06)', 'transparent']}
        style={StyleSheet.absoluteFill}
        pointerEvents="none"
      />
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>Equity Curve</Text>
        <Text style={[styles.pnl, { color: lineColor }]}>
          {latestPnl >= 0 ? '+' : ''}₹{Math.round(latestPnl).toLocaleString('en-IN')}
        </Text>
      </View>

      {/* SVG Chart */}
      <View style={styles.chartWrap}>
        <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <Defs>
            <SvgGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0%" stopColor={lineColor} stopOpacity="0.3" />
              <Stop offset="100%" stopColor={lineColor} stopOpacity="0" />
            </SvgGradient>
          </Defs>
          <Path d={areaPath} fill="url(#areaGrad)" />
          <Path d={linePath} stroke={lineColor} strokeWidth="1.5" fill="none" strokeLinejoin="round" />
        </Svg>
      </View>

      {/* Stats row */}
      <View style={styles.statsRow}>
        <StatItem label="Today" value={`${todayPnl >= 0 ? '+' : ''}₹${Math.round(todayPnl).toLocaleString('en-IN')}`} color={todayPnl >= 0 ? C.green : C.red} />
        <View style={styles.divider} />
        <StatItem label="Win Days" value={`${winRate}%`} color={C.accentBright} />
        <View style={styles.divider} />
        <StatItem label="Days" value={String(totalDays)} color={C.textSecondary} />
      </View>
    </Animated.View>
  );
}

function StatItem({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={styles.statItem}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: 20,
    marginBottom: 16,
    backgroundColor: C.card,
    borderRadius: 20,
    padding: 16,
    borderWidth: 1,
    borderColor: C.cardBorder,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  title: { fontSize: 13, fontFamily: 'Inter_500Medium', color: C.textSecondary, letterSpacing: 0.5 },
  pnl: { fontSize: 16, fontFamily: 'Inter_700Bold' },
  chartWrap: { height: 56, marginBottom: 12, borderRadius: 8, overflow: 'hidden' },
  statsRow: { flexDirection: 'row', alignItems: 'center', borderTopWidth: 1, borderTopColor: C.separator, paddingTop: 12 },
  statItem: { flex: 1, alignItems: 'center' },
  statLabel: { fontSize: 10, fontFamily: 'Inter_400Regular', color: C.textTertiary, marginBottom: 3 },
  statValue: { fontSize: 13, fontFamily: 'Inter_600SemiBold' },
  divider: { width: 1, height: 28, backgroundColor: C.separator },
});

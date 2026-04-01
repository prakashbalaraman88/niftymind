import React, { useEffect, useMemo, useRef } from "react";
import {
  View,
  Text,
  StyleSheet,
  SectionList,
  RefreshControl,
  Animated,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import colors from "@/constants/colors";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { SkeletonLoader } from "@/components/SkeletonLoader";
import type { NewsItem } from "@/types/api";

const C = colors.dark;
const IMPACT_ORDER: Record<string, number> = { high: 0, negative: 0, medium: 1, mixed: 1, low: 2, positive: 2 };

function getImpact(item: NewsItem): string {
  const d = item.details || {};
  return (d.impact as string) || (d.sentiment as string) || "";
}

function isCalendarEvent(item: NewsItem): boolean {
  return !!(item.details?.event_time as string);
}

interface Section { title: string; data: NewsItem[] }

function buildSections(items: NewsItem[]): Section[] {
  const cal: NewsItem[] = [];
  const news: NewsItem[] = [];
  for (const item of items) {
    if (isCalendarEvent(item)) cal.push(item);
    else news.push(item);
  }
  cal.sort((a, b) => {
    const ia = IMPACT_ORDER[getImpact(a)] ?? 3;
    const ib = IMPACT_ORDER[getImpact(b)] ?? 3;
    if (ia !== ib) return ia - ib;
    return new Date((a.details?.event_time as string) || a.timestamp).getTime() -
      new Date((b.details?.event_time as string) || b.timestamp).getTime();
  });
  news.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  const sections: Section[] = [];
  if (cal.length > 0) sections.push({ title: "Upcoming Events", data: cal });
  if (news.length > 0) sections.push({ title: "Market News", data: news });
  return sections;
}

export default function NewsScreen() {
  const { subscribe } = useWebSocket();
  const queryClient = useQueryClient();

  const { data, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ["news"],
    queryFn: () => api.getNews(50),
    refetchInterval: 60000,
    retry: false,
  });

  useEffect(() => {
    const unsub = subscribe("news", () => {
      queryClient.invalidateQueries({ queryKey: ["news"] });
    });
    return unsub;
  }, [subscribe, queryClient]);

  const sections = useMemo(() => buildSections(data?.news || []), [data]);

  if (isLoading) {
    return (
      <View style={styles.container}>
        <View style={styles.skeletonList}>
          {Array.from({ length: 5 }).map((_, i) => (
            <View key={i} style={styles.skeletonCard}>
              <View style={{ flexDirection: "row", gap: 12, alignItems: "flex-start" }}>
                <SkeletonLoader width={34} height={34} borderRadius={10} />
                <View style={{ flex: 1, gap: 8 }}>
                  <SkeletonLoader width="90%" height={14} />
                  <SkeletonLoader width="60%" height={12} />
                </View>
              </View>
            </View>
          ))}
        </View>
      </View>
    );
  }

  if (sections.length === 0) {
    return (
      <View style={styles.container}>
        <EmptyState icon="rss" title="No news yet" subtitle="Market news and economic events will appear here." />
      </View>
    );
  }

  const renderItem = ({ item, index }: { item: NewsItem; index: number }) => (
    <NewsCard item={item} index={index} />
  );

  const renderSectionHeader = ({ section }: { section: Section }) => (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{section.title}</Text>
      <View style={styles.sectionCountBadge}>
        <Text style={styles.sectionCount}>{section.data.length}</Text>
      </View>
    </View>
  );

  return (
    <SectionList
      style={styles.container}
      sections={sections}
      keyExtractor={(item) => String(item.id)}
      renderItem={renderItem}
      renderSectionHeader={renderSectionHeader}
      contentContainerStyle={styles.list}
      stickySectionHeadersEnabled={false}
      refreshControl={
        <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={C.accentBright} />
      }
    />
  );
}

function NewsCard({ item, index }: { item: NewsItem; index: number }) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateX = useRef(new Animated.Value(-12)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(opacity, { toValue: 1, duration: 350, delay: index * 40, useNativeDriver: true }),
      Animated.spring(translateX, { toValue: 0, delay: index * 40, useNativeDriver: true, damping: 18 }),
    ]).start();
  }, []);

  const details = item.details || {};
  const impact = getImpact(item);
  const impactVariant: "high" | "medium" | "low" =
    impact === "high" || impact === "negative" ? "high" :
    impact === "medium" || impact === "mixed" ? "medium" : "low";

  const headline = (details.headline as string) || item.message || "";
  const source = (details.source as string) || item.source || "";
  const category = (details.category as string) || item.event_type || "";
  const eventTime = (details.event_time as string) || "";
  const isCal = isCalendarEvent(item);

  const iconBgColors: [string, string] = isCal
    ? ["rgba(255,184,0,0.2)", "rgba(255,124,0,0.1)"]
    : ["rgba(124,58,237,0.2)", "rgba(37,99,235,0.1)"];

  const iconColor = isCal ? C.gold : C.accentBright;

  const impactBorderColor =
    impact === "high" || impact === "negative" ? "rgba(255,59,92,0.12)" :
    impact === "medium" || impact === "mixed" ? "rgba(255,184,0,0.12)" :
    C.cardBorder;

  return (
    <Animated.View style={{ opacity, transform: [{ translateX }] }}>
      <Card style={[styles.newsCard, { borderColor: impactBorderColor }] as any}>
        <View style={styles.newsHeader}>
          <LinearGradient colors={iconBgColors} style={styles.newsIconWrap}>
            <Feather name={isCal ? "calendar" : "file-text"} size={15} color={iconColor} />
          </LinearGradient>
          <View style={styles.newsContent}>
            <Text style={styles.newsHeadline} numberOfLines={3}>{headline}</Text>
            <View style={styles.newsMetaRow}>
              {!!source && <Text style={styles.newsSource}>{source}</Text>}
              {!!impact && <StatusBadge label={impact} variant={impactVariant} />}
              {!!category && category !== item.event_type && (
                <Text style={styles.newsCategory}>{category}</Text>
              )}
            </View>
          </View>
        </View>

        {isCal && !!eventTime && (
          <View style={styles.eventTimeRow}>
            <Feather name="clock" size={11} color={C.gold} />
            <Text style={styles.eventTimeText}>{eventTime}</Text>
          </View>
        )}

        <Text style={styles.newsTime}>{formatNewsTime(item.timestamp)}</Text>
      </Card>
    </Animated.View>
  );
}

function formatNewsTime(ts: string): string {
  try {
    const d = new Date(ts);
    const diffMins = Math.floor((Date.now() - d.getTime()) / 60000);
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    const hrs = Math.floor(diffMins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  } catch { return ""; }
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  list: { paddingHorizontal: 20, paddingTop: 4, paddingBottom: 100 },
  skeletonList: { padding: 20, gap: 12 },
  skeletonCard: { backgroundColor: C.card, borderRadius: 20, padding: 16, borderWidth: 1, borderColor: C.cardBorder },
  sectionHeader: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingVertical: 12, paddingTop: 20,
  },
  sectionTitle: { fontSize: 16, fontFamily: "Inter_600SemiBold", color: C.text },
  sectionCountBadge: { backgroundColor: C.elevated, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 2 },
  sectionCount: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.textSecondary },
  newsCard: { marginBottom: 10 },
  newsHeader: { flexDirection: "row", alignItems: "flex-start" },
  newsIconWrap: { width: 34, height: 34, borderRadius: 10, justifyContent: "center", alignItems: "center", marginRight: 12, marginTop: 1 },
  newsContent: { flex: 1 },
  newsHeadline: { fontSize: 14, fontFamily: "Inter_500Medium", color: C.text, lineHeight: 20, marginBottom: 6 },
  newsMetaRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  newsSource: { fontSize: 11, fontFamily: "Inter_500Medium", color: C.textSecondary },
  newsCategory: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary },
  eventTimeRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: C.separator },
  eventTimeText: { fontSize: 12, fontFamily: "Inter_600SemiBold", color: C.gold },
  newsTime: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary, marginTop: 8, textAlign: "right" },
});

import React, { useEffect, useMemo } from "react";
import {
  View,
  Text,
  StyleSheet,
  SectionList,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import colors from "@/constants/colors";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import type { NewsItem } from "@/types/api";

const IMPACT_ORDER: Record<string, number> = { high: 0, negative: 0, medium: 1, mixed: 1, low: 2, positive: 2 };

function getImpact(item: NewsItem): string {
  const d = item.details || {};
  return (d.impact as string) || (d.sentiment as string) || "";
}

function isCalendarEvent(item: NewsItem): boolean {
  const d = item.details || {};
  return !!(d.event_time as string);
}

interface Section {
  title: string;
  data: NewsItem[];
}

function buildSections(items: NewsItem[]): Section[] {
  const calendarEvents: NewsItem[] = [];
  const newsItems: NewsItem[] = [];

  for (const item of items) {
    if (isCalendarEvent(item)) {
      calendarEvents.push(item);
    } else {
      newsItems.push(item);
    }
  }

  calendarEvents.sort((a, b) => {
    const ia = IMPACT_ORDER[getImpact(a)] ?? 3;
    const ib = IMPACT_ORDER[getImpact(b)] ?? 3;
    if (ia !== ib) return ia - ib;
    const ta = (a.details?.event_time as string) || a.timestamp;
    const tb = (b.details?.event_time as string) || b.timestamp;
    return new Date(ta).getTime() - new Date(tb).getTime();
  });

  newsItems.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

  const sections: Section[] = [];
  if (calendarEvents.length > 0) {
    sections.push({ title: "Upcoming Events", data: calendarEvents });
  }
  if (newsItems.length > 0) {
    sections.push({ title: "Market News", data: newsItems });
  }
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

  const renderItem = ({ item }: { item: NewsItem }) => {
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
    const icon = isCal ? "calendar" : "file-text";

    return (
      <Card style={styles.newsCard}>
        <View style={styles.newsHeader}>
          <View style={[styles.newsIconWrap, {
            backgroundColor: isCal ? colors.light.yellowLight : colors.light.tintLight,
          }]}>
            <Feather
              name={icon}
              size={16}
              color={isCal ? colors.light.yellow : colors.light.tint}
            />
          </View>
          <View style={styles.newsContent}>
            <Text style={styles.newsHeadline} numberOfLines={3}>
              {headline}
            </Text>
            <View style={styles.newsMetaRow}>
              {!!source && <Text style={styles.newsSource}>{source}</Text>}
              {!!impact && (
                <StatusBadge label={impact} variant={impactVariant} />
              )}
              {!!category && category !== item.event_type && (
                <Text style={styles.newsCategory}>{category}</Text>
              )}
            </View>
          </View>
        </View>

        {isCal && !!eventTime && (
          <View style={styles.eventTimeRow}>
            <Feather name="clock" size={12} color={colors.light.yellow} />
            <Text style={styles.eventTimeText}>{eventTime}</Text>
          </View>
        )}

        <Text style={styles.newsTime}>{formatNewsTime(item.timestamp)}</Text>
      </Card>
    );
  };

  const renderSectionHeader = ({ section }: { section: Section }) => (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{section.title}</Text>
      <Text style={styles.sectionCount}>{section.data.length}</Text>
    </View>
  );

  if (isLoading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator color={colors.light.tint} />
      </View>
    );
  }

  if (sections.length === 0) {
    return (
      <View style={styles.container}>
        <EmptyState
          icon="rss"
          title="No news yet"
          subtitle="Market news and economic events will appear here when Agent 6 starts classifying."
        />
      </View>
    );
  }

  return (
    <SectionList
      style={styles.container}
      sections={sections}
      keyExtractor={(item) => String(item.id)}
      renderItem={renderItem}
      renderSectionHeader={renderSectionHeader}
      contentContainerStyle={styles.list}
      contentInsetAdjustmentBehavior="automatic"
      stickySectionHeadersEnabled={false}
      refreshControl={
        <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={colors.light.tint} />
      }
    />
  );
}

function formatNewsTime(ts: string): string {
  try {
    const d = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    const hrs = Math.floor(diffMins / 60);
    if (hrs < 24) return `${hrs}h ago`;

    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  } catch {
    return "";
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.light.background,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: colors.light.background,
  },
  list: {
    paddingHorizontal: 20,
    paddingTop: 4,
    paddingBottom: 100,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 10,
    paddingTop: 16,
  },
  sectionTitle: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  sectionCount: {
    fontSize: 13,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
  },
  newsCard: {
    marginBottom: 10,
  },
  newsHeader: {
    flexDirection: "row",
    alignItems: "flex-start",
  },
  newsIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 8,
    justifyContent: "center",
    alignItems: "center",
    marginRight: 10,
    marginTop: 2,
  },
  newsContent: {
    flex: 1,
  },
  newsHeadline: {
    fontSize: 14,
    fontFamily: "Inter_500Medium",
    color: colors.light.text,
    lineHeight: 20,
    marginBottom: 6,
  },
  newsMetaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  newsSource: {
    fontSize: 11,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
  },
  newsCategory: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: colors.light.textTertiary,
  },
  eventTimeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: colors.light.border,
  },
  eventTimeText: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.yellow,
  },
  newsTime: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: colors.light.textTertiary,
    marginTop: 8,
    textAlign: "right",
  },
});

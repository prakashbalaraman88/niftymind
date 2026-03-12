import React, { useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
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

  const news = data?.news || [];

  const renderItem = ({ item }: { item: NewsItem }) => {
    const details = item.details || {};
    const impact = (details.impact as string) || (details.sentiment as string) || "";
    const impactVariant: "high" | "medium" | "low" =
      impact === "high" || impact === "negative" ? "high" :
      impact === "medium" || impact === "mixed" ? "medium" : "low";

    const headline = (details.headline as string) || item.message || "";
    const source = (details.source as string) || item.source || "";
    const category = (details.category as string) || item.event_type || "";
    const eventTime = (details.event_time as string) || "";

    const isCalendarEvent = item.event_type === "NEWS_SIGNAL" && !!eventTime;
    const icon = isCalendarEvent ? "calendar" : "file-text";

    return (
      <Card style={styles.newsCard}>
        <View style={styles.newsHeader}>
          <View style={[styles.newsIconWrap, {
            backgroundColor: isCalendarEvent ? colors.light.yellowLight : colors.light.tintLight,
          }]}>
            <Feather
              name={icon}
              size={16}
              color={isCalendarEvent ? colors.light.yellow : colors.light.tint}
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

        {isCalendarEvent && !!eventTime && (
          <View style={styles.eventTimeRow}>
            <Feather name="clock" size={12} color={colors.light.yellow} />
            <Text style={styles.eventTimeText}>{eventTime}</Text>
          </View>
        )}

        <Text style={styles.newsTime}>{formatNewsTime(item.timestamp)}</Text>
      </Card>
    );
  };

  return (
    <View style={styles.container}>
      <FlatList
        data={news}
        keyExtractor={(item) => String(item.id)}
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
            <EmptyState
              icon="rss"
              title="No news yet"
              subtitle="Market news and economic events will appear here when Agent 6 starts classifying."
            />
          )
        }
      />
    </View>
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
  list: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 100,
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

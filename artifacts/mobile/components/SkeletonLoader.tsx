import React, { useEffect, useRef } from "react";
import { View, Animated, StyleSheet, type ViewStyle } from "react-native";
import colors from "@/constants/colors";

const C = colors.dark;

interface Props {
  width?: number | string;
  height?: number;
  borderRadius?: number;
  style?: ViewStyle;
}

export function SkeletonLoader({ width = "100%", height = 16, borderRadius = 8, style }: Props) {
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, { toValue: 1, duration: 900, useNativeDriver: false }),
        Animated.timing(shimmer, { toValue: 0, duration: 900, useNativeDriver: false }),
      ])
    );
    animation.start();
    return () => animation.stop();
  }, [shimmer]);

  const backgroundColor = shimmer.interpolate({
    inputRange: [0, 1],
    outputRange: [C.shimmer1, C.shimmer2],
  });

  return (
    <Animated.View
      style={[
        {
          width: width as ViewStyle["width"],
          height,
          borderRadius,
          backgroundColor,
        },
        style,
      ]}
    />
  );
}

export function CardSkeleton() {
  return (
    <View style={styles.card}>
      <SkeletonLoader width={100} height={12} borderRadius={6} />
      <View style={{ height: 14 }} />
      <SkeletonLoader width="70%" height={22} borderRadius={8} />
      <View style={{ height: 10 }} />
      <SkeletonLoader width="50%" height={14} borderRadius={6} />
      <View style={{ height: 14, borderTopWidth: 1, borderTopColor: C.separator, marginTop: 14 }} />
      <View style={styles.skeletonRow}>
        <SkeletonLoader width="30%" height={12} borderRadius={6} />
        <SkeletonLoader width="25%" height={12} borderRadius={6} />
        <SkeletonLoader width="28%" height={12} borderRadius={6} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: C.card,
    borderRadius: 20,
    padding: 16,
    marginHorizontal: 20,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: C.cardBorder,
  },
  skeletonRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
});

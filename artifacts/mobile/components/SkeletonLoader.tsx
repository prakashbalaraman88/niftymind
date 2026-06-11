import React, { useEffect, useState } from "react";
import {
  View,
  StyleSheet,
  type ViewStyle,
  type LayoutChangeEvent,
} from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  Easing,
} from "react-native-reanimated";
import { LinearGradient } from "expo-linear-gradient";
import colors from "@/constants/colors";

const C = colors.dark;

interface Props {
  width?: number | string;
  height?: number;
  borderRadius?: number;
  style?: ViewStyle;
}

export function SkeletonLoader({ width = "100%", height = 16, borderRadius = 8, style }: Props) {
  const [containerWidth, setContainerWidth] = useState(200);
  const translateX = useSharedValue(-containerWidth * 1.5);

  useEffect(() => {
    translateX.value = -containerWidth * 1.5;
    translateX.value = withRepeat(
      withTiming(containerWidth * 1.5, {
        duration: 1200,
        easing: Easing.linear,
      }),
      -1,
      false,
    );
  }, [containerWidth]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: translateX.value }],
  }));

  const onLayout = (e: LayoutChangeEvent) => {
    const w = e.nativeEvent.layout.width;
    if (w > 0) setContainerWidth(w);
  };

  return (
    <View
      onLayout={onLayout}
      style={[
        {
          width: width as ViewStyle["width"],
          height,
          borderRadius,
          backgroundColor: C.shimmer1,
          overflow: "hidden",
        },
        style,
      ]}
    >
      <Animated.View style={[StyleSheet.absoluteFill, animatedStyle]}>
        <LinearGradient
          colors={[
            "transparent",
            C.shimmer2,
            C.shimmer3,
            C.shimmer2,
            "transparent",
          ]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
          style={{ width: containerWidth * 3, height: "100%" }}
        />
      </Animated.View>
    </View>
  );
}

export function CardSkeleton() {
  return (
    <View style={styles.card}>
      <SkeletonLoader width={100} height={12} borderRadius={6} />
      <View style={{ height: 14 }} />
      <SkeletonLoader width="70%" height={28} borderRadius={8} />
      <View style={{ height: 10 }} />
      <SkeletonLoader width="50%" height={14} borderRadius={6} />
      <View style={styles.divider} />
      <View style={styles.skeletonRow}>
        <SkeletonLoader width="30%" height={12} borderRadius={6} />
        <SkeletonLoader width="25%" height={12} borderRadius={6} />
        <SkeletonLoader width="28%" height={12} borderRadius={6} />
      </View>
      <View style={{ height: 10 }} />
      <View style={styles.skeletonRow}>
        <SkeletonLoader width="40%" height={10} borderRadius={6} />
        <SkeletonLoader width="35%" height={10} borderRadius={6} />
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
  divider: {
    height: 1,
    backgroundColor: C.separator,
    marginVertical: 14,
  },
  skeletonRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
});

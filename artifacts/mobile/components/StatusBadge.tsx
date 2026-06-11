import React, { useEffect } from "react";
import { View, Text, StyleSheet } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import colors from "@/constants/colors";

const C = colors.dark;

type Variant =
  | "bullish" | "bearish" | "neutral"
  | "active" | "inactive"
  | "paper" | "live"
  | "high" | "medium" | "low"
  | "warning" | "scalp";

const VARIANT_COLORS: Record<Variant, { bg: string; text: string; border: string }> = {
  bullish:  { bg: C.greenDark,                      text: C.green,        border: "rgba(16,240,160,0.2)" },
  bearish:  { bg: C.redDark,                        text: C.red,          border: "rgba(255,59,92,0.2)" },
  neutral:  { bg: "rgba(255,255,255,0.06)",         text: C.textSecondary, border: "rgba(255,255,255,0.1)" },
  active:   { bg: C.greenDark,                      text: C.green,        border: "rgba(16,240,160,0.2)" },
  inactive: { bg: "rgba(255,255,255,0.06)",         text: C.textTertiary, border: "rgba(255,255,255,0.08)" },
  paper:    { bg: C.accentLight,                    text: C.accentBright, border: "rgba(124,58,237,0.2)" },
  live:     { bg: C.redDark,                        text: C.red,          border: "rgba(255,59,92,0.2)" },
  high:     { bg: C.redDark,                        text: C.red,          border: "rgba(255,59,92,0.2)" },
  medium:   { bg: C.goldDark,                       text: C.gold,         border: "rgba(255,184,0,0.2)" },
  low:      { bg: C.greenDark,                      text: C.green,        border: "rgba(16,240,160,0.2)" },
  warning:  { bg: C.goldDark,                       text: C.gold,         border: "rgba(255,184,0,0.2)" },
  scalp:    { bg: "rgba(0,220,255,0.12)",           text: "#00DCFF",      border: "rgba(0,220,255,0.2)" },
};

interface Props {
  label: string;
  variant: Variant;
  size?: "small" | "medium";
  pulse?: boolean;
}

export function StatusBadge({ label, variant, size = "small", pulse = false }: Props) {
  const c = VARIANT_COLORS[variant] ?? VARIANT_COLORS.neutral;
  const isSmall = size === "small";

  const opacity = useSharedValue(1);

  useEffect(() => {
    if (!pulse) {
      opacity.value = 1;
      return;
    }
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.7, { duration: 700 }),
        withTiming(1.0, { duration: 700 }),
      ),
      -1,
      false,
    );
  }, [pulse]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <Animated.View
      style={[
        styles.badge,
        { backgroundColor: c.bg, borderColor: c.border },
        isSmall ? styles.small : styles.medium,
        animatedStyle,
      ]}
    >
      <Text
        style={[
          styles.text,
          { color: c.text },
          isSmall ? styles.textSmall : styles.textMedium,
        ]}
      >
        {label.toUpperCase()}
      </Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderRadius: 8,
    alignSelf: "flex-start",
    borderWidth: 1,
  },
  small:      { paddingHorizontal: 8,  paddingVertical: 3 },
  medium:     { paddingHorizontal: 10, paddingVertical: 5 },
  text:       { fontFamily: "Inter_600SemiBold", letterSpacing: 0.6 },
  textSmall:  { fontSize: 10 },
  textMedium: { fontSize: 11 },
});

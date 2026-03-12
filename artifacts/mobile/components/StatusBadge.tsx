import React from "react";
import { View, Text, StyleSheet } from "react-native";
import colors from "@/constants/colors";

type Variant = "bullish" | "bearish" | "neutral" | "active" | "inactive" | "paper" | "live" | "high" | "medium" | "low";

const VARIANT_COLORS: Record<Variant, { bg: string; text: string }> = {
  bullish: { bg: colors.light.greenLight, text: colors.light.green },
  bearish: { bg: colors.light.redLight, text: colors.light.red },
  neutral: { bg: "#F3F4F6", text: colors.light.textSecondary },
  active: { bg: colors.light.greenLight, text: colors.light.green },
  inactive: { bg: "#F3F4F6", text: colors.light.textSecondary },
  paper: { bg: colors.light.tintLight, text: colors.light.tint },
  live: { bg: colors.light.redLight, text: colors.light.red },
  high: { bg: colors.light.redLight, text: colors.light.red },
  medium: { bg: colors.light.yellowLight, text: colors.light.yellow },
  low: { bg: colors.light.greenLight, text: colors.light.green },
};

interface Props {
  label: string;
  variant: Variant;
  size?: "small" | "medium";
}

export function StatusBadge({ label, variant, size = "small" }: Props) {
  const c = VARIANT_COLORS[variant] || VARIANT_COLORS.neutral;
  const isSmall = size === "small";
  return (
    <View style={[styles.badge, { backgroundColor: c.bg }, isSmall ? styles.small : styles.medium]}>
      <Text style={[styles.text, { color: c.text }, isSmall ? styles.textSmall : styles.textMedium]}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderRadius: 6,
    alignSelf: "flex-start" as const,
  },
  small: {
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  medium: {
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  text: {
    fontFamily: "Inter_600SemiBold",
    textTransform: "uppercase" as const,
  },
  textSmall: {
    fontSize: 10,
    letterSpacing: 0.5,
  },
  textMedium: {
    fontSize: 11,
    letterSpacing: 0.5,
  },
});

import React from "react";
import { Text, type TextStyle } from "react-native";
import colors from "@/constants/colors";

interface Props {
  value: number | null | undefined;
  prefix?: string;
  style?: TextStyle;
  showSign?: boolean;
}

export function PnlText({ value, prefix = "", style, showSign = true }: Props) {
  const num = value ?? 0;
  const isPositive = num > 0;
  const isNeutral = num === 0;
  const color = isNeutral ? colors.light.textSecondary : isPositive ? colors.light.green : colors.light.red;
  const sign = showSign ? (isPositive ? "+" : "") : "";
  const formatted = `${prefix}${sign}${num.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

  return (
    <Text style={[{ color, fontFamily: "Inter_600SemiBold" }, style]}>
      {formatted}
    </Text>
  );
}

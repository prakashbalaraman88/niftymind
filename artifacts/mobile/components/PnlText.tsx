import React, { useEffect, useRef } from "react";
import { Animated, Text, type TextStyle } from "react-native";
import colors from "@/constants/colors";

const C = colors.dark;

interface Props {
  value: number | null | undefined;
  prefix?: string;
  style?: TextStyle;
  showSign?: boolean;
  animate?: boolean;
}

export function PnlText({ value, prefix = "", style, showSign = true, animate = false }: Props) {
  const num = value ?? 0;
  const isPositive = num > 0;
  const isNeutral = num === 0;
  const color = isNeutral ? C.textSecondary : isPositive ? C.green : C.red;
  const sign = showSign ? (isPositive ? "+" : "") : "";
  const formatted = `${prefix}${sign}${num.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

  const glowOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!animate || isNeutral) return;
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(glowOpacity, { toValue: 1, duration: 1000, useNativeDriver: true }),
        Animated.timing(glowOpacity, { toValue: 0.3, duration: 1000, useNativeDriver: true }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [num, animate]);

  return (
    <Text
      style={[
        {
          color,
          fontFamily: "Inter_700Bold",
          textShadowColor: isNeutral ? "transparent" : isPositive ? C.greenGlow : C.redGlow,
          textShadowOffset: { width: 0, height: 0 },
          textShadowRadius: 12,
        },
        style,
      ]}
    >
      {formatted}
    </Text>
  );
}

import React, { useEffect, useRef } from "react";
import { type TextStyle } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import colors from "@/constants/colors";

const C = colors.dark;

const SIZE_MAP = {
  small:  12,
  medium: 15,
  large:  20,
} as const;

interface Props {
  value: number | null | undefined;
  prefix?: string;
  style?: TextStyle;
  showSign?: boolean;
  animate?: boolean;
  // New props
  size?: "small" | "medium" | "large";
  showArrow?: boolean;
}

export function PnlText({
  value,
  prefix = "",
  style,
  showSign = true,
  animate = false,
  size,
  showArrow = false,
}: Props) {
  const num = value ?? 0;
  const isPositive = num > 0;
  const isNeutral = num === 0;
  const color = isNeutral ? C.textSecondary : isPositive ? C.green : C.red;

  const sign = showSign ? (isPositive ? "+" : "") : "";
  const arrow = showArrow ? (isPositive ? "▲" : isNeutral ? "" : "▼") : "";
  const formatted = `${arrow}${prefix}${sign}${num.toLocaleString("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;

  const glowOpacity = useSharedValue(animate && !isNeutral ? 0.3 : 1);
  const scaleVal = useSharedValue(1);
  const prevValueRef = useRef<number | null | undefined>(undefined);

  // Glow pulse when animate=true
  useEffect(() => {
    if (!animate || isNeutral) {
      glowOpacity.value = 1;
      return;
    }
    glowOpacity.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 1000 }),
        withTiming(0.3, { duration: 1000 }),
      ),
      -1,
      false,
    );
  }, [animate, isNeutral]);

  // Scale bump when value changes significantly (>5% relative change)
  useEffect(() => {
    const prev = prevValueRef.current;
    prevValueRef.current = value;

    if (prev === undefined || prev === null || num === 0) return;
    const pct = Math.abs((num - prev) / (Math.abs(prev) || 1));
    if (pct > 0.05) {
      scaleVal.value = withSequence(
        withTiming(1.12, { duration: 150 }),
        withTiming(1.0, { duration: 200 }),
      );
    }
  }, [num]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: glowOpacity.value,
    transform: [{ scale: scaleVal.value }],
  }));

  const fontSize = size ? SIZE_MAP[size] : undefined;

  return (
    <Animated.Text
      style={[
        {
          color,
          fontFamily: "Inter_700Bold",
          textShadowColor: isNeutral ? "transparent" : isPositive ? C.greenGlow : C.redGlow,
          textShadowOffset: { width: 0, height: 0 },
          textShadowRadius: 12,
          ...(fontSize !== undefined ? { fontSize } : {}),
        },
        style,
        animatedStyle,
      ]}
    >
      {formatted}
    </Animated.Text>
  );
}

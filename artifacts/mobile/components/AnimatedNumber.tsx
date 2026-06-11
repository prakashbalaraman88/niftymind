import React, { useEffect, useRef, useState } from "react";
import { Animated as RNAnimated, Easing, type TextStyle } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSequence,
  withTiming,
  interpolateColor,
} from "react-native-reanimated";

interface Props {
  value: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  style?: TextStyle;
  decimals?: number;
  formatFn?: (n: number) => string;
  flash?: boolean;
}

export function AnimatedNumber({
  value,
  duration = 800,
  prefix = "",
  suffix = "",
  style,
  decimals = 0,
  formatFn,
  flash = false,
}: Props) {
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);
  const listenerIdRef = useRef<string | null>(null);
  const animValue = useRef(new RNAnimated.Value(value)).current;

  const flashProgress = useSharedValue(0);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = value;

    if (listenerIdRef.current) {
      animValue.removeListener(listenerIdRef.current);
    }

    animValue.setValue(prev);

    const id = animValue.addListener(({ value: v }) => {
      setDisplay(v);
    });
    listenerIdRef.current = id;

    RNAnimated.timing(animValue, {
      toValue: value,
      duration,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false,
    }).start(() => {
      animValue.removeListener(id);
      listenerIdRef.current = null;
    });

    if (flash && prev !== value) {
      flashProgress.value = withSequence(
        withTiming(1, { duration: 120 }),
        withTiming(0, { duration: 350 }),
      );
    }

    return () => {
      if (listenerIdRef.current) {
        animValue.removeListener(listenerIdRef.current);
      }
    };
  }, [value]);

  const baseColor = (style?.color as string) ?? "#FFFFFF";

  const flashStyle = useAnimatedStyle(() => {
    const color = interpolateColor(
      flashProgress.value,
      [0, 1],
      [baseColor, "#FFEB80"],
    );
    return { color };
  });

  const text = formatFn
    ? formatFn(display)
    : `${prefix}${display.toLocaleString("en-IN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}${suffix}`;

  return (
    <Animated.Text style={[style, flash ? flashStyle : undefined]}>
      {text}
    </Animated.Text>
  );
}

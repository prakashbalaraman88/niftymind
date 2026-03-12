import React, { useEffect, useRef, useState } from "react";
import { Animated, Text, type TextStyle } from "react-native";

interface Props {
  value: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  style?: TextStyle;
  decimals?: number;
  formatFn?: (n: number) => string;
}

export function AnimatedNumber({
  value,
  duration = 800,
  prefix = "",
  suffix = "",
  style,
  decimals = 0,
  formatFn,
}: Props) {
  const animValue = useRef(new Animated.Value(value)).current;
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = value;
    animValue.setValue(prev);

    const listener = animValue.addListener(({ value: v }) => {
      setDisplay(v);
    });

    Animated.timing(animValue, {
      toValue: value,
      duration,
      useNativeDriver: false,
    }).start(() => {
      animValue.removeListener(listener);
    });

    return () => animValue.removeListener(listener);
  }, [value]);

  const text = formatFn
    ? formatFn(display)
    : `${prefix}${display.toLocaleString("en-IN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}${suffix}`;

  return <Text style={style}>{text}</Text>;
}

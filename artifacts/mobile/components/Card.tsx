import React, { useRef } from "react";
import {
  Animated,
  Pressable,
  StyleSheet,
  View,
  type ViewStyle,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import colors from "@/constants/colors";

const C = colors.dark;

interface Props {
  children: React.ReactNode;
  style?: ViewStyle;
  onPress?: () => void;
  gradient?: boolean;
  glow?: string;
}

export function Card({ children, style, onPress, gradient = false, glow }: Props) {
  const pressScale = useRef(new Animated.Value(1)).current;

  const onPressIn = () => {
    if (!onPress) return;
    Animated.spring(pressScale, {
      toValue: 0.97,
      speed: 50,
      bounciness: 2,
      useNativeDriver: true,
    }).start();
  };

  const onPressOut = () => {
    if (!onPress) return;
    Animated.spring(pressScale, {
      toValue: 1,
      speed: 40,
      bounciness: 6,
      useNativeDriver: true,
    }).start();
  };

  const inner = gradient ? (
    <LinearGradient
      colors={C.gradient.card}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={[styles.card, style]}
    >
      {children}
    </LinearGradient>
  ) : (
    <View style={[styles.card, style]}>{children}</View>
  );

  if (onPress) {
    return (
      <Animated.View style={{ transform: [{ scale: pressScale }] }}>
        {glow && (
          <View style={[styles.glowBg, { shadowColor: glow }]} />
        )}
        <Pressable onPress={onPress} onPressIn={onPressIn} onPressOut={onPressOut}>
          {inner}
        </Pressable>
      </Animated.View>
    );
  }

  return (
    <View>
      {glow && <View style={[styles.glowBg, { shadowColor: glow }]} />}
      {inner}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: C.card,
    borderRadius: 20,
    padding: 16,
    borderWidth: 1,
    borderColor: C.cardBorder,
    overflow: "hidden",
  },
  glowBg: {
    position: "absolute",
    inset: 0,
    borderRadius: 20,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.4,
    shadowRadius: 20,
    elevation: 0,
  },
});

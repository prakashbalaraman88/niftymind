import React from "react";
import {
  View,
  type ViewStyle,
  StyleSheet,
  Pressable,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
} from "react-native-reanimated";
import { GestureDetector, Gesture } from "react-native-gesture-handler";
import colors from "@/constants/colors";

const C = colors.dark;

type Variant = "default" | "glass" | "elevated";

const VARIANT_STYLES: Record<Variant, { backgroundColor: string; borderColor: string }> = {
  default: { backgroundColor: "#1A1C24", borderColor: "rgba(255,255,255,0.07)" },
  glass: { backgroundColor: "rgba(26,28,36,0.8)", borderColor: "rgba(255,255,255,0.10)" },
  elevated: { backgroundColor: "#16181E", borderColor: "rgba(255,255,255,0.05)" },
};

interface Props {
  children: React.ReactNode;
  style?: ViewStyle;
  onPress?: () => void;
  gradient?: boolean;
  glow?: string;
  // New props
  glowColor?: string;
  accentColor?: string;
  variant?: Variant;
}

export function Card({
  children,
  style,
  onPress,
  gradient = false,
  glow,
  glowColor,
  accentColor,
  variant = "default",
}: Props) {
  const scale = useSharedValue(1);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const tap = Gesture.Tap()
    .onBegin(() => {
      if (onPress) {
        scale.value = withSpring(0.97, { mass: 0.5, damping: 15, stiffness: 300 });
      }
    })
    .onFinalize(() => {
      if (onPress) {
        scale.value = withSpring(1, { mass: 0.5, damping: 12, stiffness: 200 });
      }
    })
    .onEnd(() => {
      if (onPress) {
        onPress();
      }
    });

  const variantStyle = VARIANT_STYLES[variant];
  const effectiveGlow = glowColor ?? glow;

  const cardStyle: ViewStyle = {
    backgroundColor: variantStyle.backgroundColor,
    borderRadius: 20,
    padding: 16,
    borderWidth: 1,
    borderColor: variantStyle.borderColor,
    overflow: "hidden",
  };

  const inner = gradient ? (
    <LinearGradient
      colors={C.gradient.card}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={[cardStyle, style]}
    >
      {accentColor && (
        <View
          style={[styles.accentLine, { backgroundColor: accentColor }]}
          pointerEvents="none"
        />
      )}
      {children}
    </LinearGradient>
  ) : (
    <View style={[cardStyle, style]}>
      {accentColor && (
        <View
          style={[styles.accentLine, { backgroundColor: accentColor }]}
          pointerEvents="none"
        />
      )}
      {children}
    </View>
  );

  if (onPress) {
    return (
      <GestureDetector gesture={tap}>
        <Animated.View style={animatedStyle}>
          {effectiveGlow && (
            <View
              style={[styles.glowBg, { shadowColor: effectiveGlow }]}
              pointerEvents="none"
            />
          )}
          {inner}
        </Animated.View>
      </GestureDetector>
    );
  }

  return (
    <View>
      {effectiveGlow && (
        <View
          style={[styles.glowBg, { shadowColor: effectiveGlow }]}
          pointerEvents="none"
        />
      )}
      {inner}
    </View>
  );
}

const styles = StyleSheet.create({
  glowBg: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderRadius: 20,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.4,
    shadowRadius: 20,
    elevation: 0,
  },
  accentLine: {
    position: "absolute",
    top: 0,
    left: 0,
    bottom: 0,
    width: 2,
    zIndex: 1,
  },
});

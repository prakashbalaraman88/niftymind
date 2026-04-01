import React, { useRef, useEffect } from "react";
import { View, Text, StyleSheet, Pressable, Animated } from "react-native";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import colors from "@/constants/colors";

const C = colors.dark;

interface Props {
  icon: string;
  title: string;
  subtitle?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({ icon, title, subtitle, actionLabel, onAction }: Props) {
  const opacity = useRef(new Animated.Value(0)).current;
  const scale = useRef(new Animated.Value(0.85)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(scale, { toValue: 1, useNativeDriver: true, damping: 14, mass: 0.8 }),
      Animated.timing(opacity, { toValue: 1, duration: 500, useNativeDriver: true }),
    ]).start();
  }, []);

  return (
    <Animated.View style={[styles.container, { opacity, transform: [{ scale }] }]}>
      <LinearGradient
        colors={["rgba(124,58,237,0.15)", "rgba(37,99,235,0.08)"]}
        style={styles.iconWrap}
      >
        <Feather name={icon as never} size={32} color={C.accentBright} />
      </LinearGradient>
      <Text style={styles.title}>{title}</Text>
      {!!subtitle && <Text style={styles.subtitle}>{subtitle}</Text>}
      {!!actionLabel && !!onAction && (
        <Pressable onPress={onAction} style={({ pressed }) => [styles.button, pressed && styles.pressed]}>
          <LinearGradient
            colors={C.gradient.accent}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 0 }}
            style={styles.buttonGradient}
          >
            <Text style={styles.buttonText}>{actionLabel}</Text>
          </LinearGradient>
        </Pressable>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 40,
    paddingVertical: 60,
  },
  iconWrap: {
    width: 72,
    height: 72,
    borderRadius: 24,
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 20,
    borderWidth: 1,
    borderColor: "rgba(124,58,237,0.2)",
  },
  title: {
    fontSize: 18,
    fontFamily: "Inter_600SemiBold",
    color: C.text,
    textAlign: "center",
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    fontFamily: "Inter_400Regular",
    color: C.textSecondary,
    textAlign: "center",
    lineHeight: 22,
  },
  button: {
    marginTop: 24,
    borderRadius: 14,
    overflow: "hidden",
  },
  buttonGradient: {
    paddingHorizontal: 24,
    paddingVertical: 12,
  },
  pressed: { opacity: 0.8 },
  buttonText: {
    fontSize: 14,
    fontFamily: "Inter_600SemiBold",
    color: "#fff",
  },
});

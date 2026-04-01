import React, { useEffect, useRef } from "react";
import { Animated, Dimensions, StyleSheet, View } from "react-native";

const { width: W, height: H } = Dimensions.get("window");
const COLORS = ["#10F0A0", "#FFB800", "#8B5CF6", "#FF3B5C", "#2563EB", "#FF9F43", "#00D4FF"];
const COUNT = 70;

interface Particle {
  x: Animated.Value;
  y: Animated.Value;
  rot: Animated.Value;
  scale: Animated.Value;
  opacity: Animated.Value;
  color: string;
  shape: "rect" | "circle" | "diamond";
  initX: number;
}

function makeParticle(): Particle {
  return {
    x: new Animated.Value(0),
    y: new Animated.Value(0),
    rot: new Animated.Value(0),
    scale: new Animated.Value(0),
    opacity: new Animated.Value(0),
    color: COLORS[Math.floor(Math.random() * COLORS.length)],
    shape: (["rect", "circle", "diamond"] as const)[Math.floor(Math.random() * 3)],
    initX: Math.random() * W,
  };
}

interface Props {
  active: boolean;
  onComplete?: () => void;
}

export function Confetti({ active, onComplete }: Props) {
  const particles = useRef<Particle[]>(
    Array.from({ length: COUNT }, makeParticle)
  ).current;
  const anim = useRef<Animated.CompositeAnimation | null>(null);

  useEffect(() => {
    if (!active) return;

    particles.forEach((p) => {
      p.x.setValue(p.initX);
      p.y.setValue(-30);
      p.rot.setValue(0);
      p.scale.setValue(0);
      p.opacity.setValue(0);
    });

    const animations = particles.map((p) => {
      const delay = Math.random() * 600;
      const dur = 1800 + Math.random() * 1200;
      const tx = p.initX + (Math.random() - 0.5) * 240;
      const ty = H * 0.65 + Math.random() * 150;
      const rotEnd = (Math.random() - 0.5) * 1080;
      const sc = 0.4 + Math.random() * 1;

      return Animated.parallel([
        Animated.sequence([
          Animated.timing(p.scale, { toValue: sc, duration: 200, delay, useNativeDriver: true }),
        ]),
        Animated.timing(p.x, { toValue: tx, duration: dur, delay, useNativeDriver: true }),
        Animated.timing(p.y, { toValue: ty, duration: dur, delay, useNativeDriver: true }),
        Animated.timing(p.rot, { toValue: rotEnd, duration: dur, delay, useNativeDriver: true }),
        Animated.sequence([
          Animated.timing(p.opacity, { toValue: 1, duration: 100, delay, useNativeDriver: true }),
          Animated.timing(p.opacity, { toValue: 1, duration: dur - 500, delay: delay + 100, useNativeDriver: true }),
          Animated.timing(p.opacity, { toValue: 0, duration: 400, useNativeDriver: true }),
        ]),
      ]);
    });

    anim.current = Animated.parallel(animations);
    anim.current.start(({ finished }) => {
      if (finished && onComplete) onComplete();
    });

    return () => anim.current?.stop();
  }, [active]);

  if (!active) return null;

  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      {particles.map((p, i) => {
        const rotate = p.rot.interpolate({
          inputRange: [-1080, 1080],
          outputRange: ["-1080deg", "1080deg"],
        });
        const size = 6 + (i % 5) * 2;
        const isCircle = p.shape === "circle";
        const isDiamond = p.shape === "diamond";
        return (
          <Animated.View
            key={i}
            style={[
              styles.particle,
              {
                width: size,
                height: size,
                borderRadius: isCircle ? size / 2 : 1,
                backgroundColor: p.color,
                left: 0,
                top: 0,
                transform: [
                  { translateX: p.x },
                  { translateY: p.y },
                  { rotate },
                  { scale: p.scale },
                  ...(isDiamond ? [{ rotate: "45deg" as const }] : []),
                ],
                opacity: p.opacity,
              },
            ]}
          />
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  particle: {
    position: "absolute",
  },
});

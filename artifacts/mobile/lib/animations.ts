import { useEffect, useRef } from "react";
import { Animated, Easing } from "react-native";

export function useEntrance(delay = 0) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(24)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 1,
        duration: 500,
        delay,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        toValue: 0,
        duration: 500,
        delay,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
    ]).start();
  }, []);

  return { opacity, translateY };
}

export function useStaggeredEntrance(count: number, delayBetween = 60) {
  const anims = Array.from({ length: count }, (_, i) => ({
    opacity: useRef(new Animated.Value(0)).current,
    translateY: useRef(new Animated.Value(20)).current,
  }));

  useEffect(() => {
    const animations = anims.flatMap(({ opacity, translateY }, i) => [
      Animated.timing(opacity, {
        toValue: 1,
        duration: 400,
        delay: i * delayBetween,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        toValue: 0,
        duration: 400,
        delay: i * delayBetween,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }),
    ]);
    Animated.parallel(animations).start();
  }, []);

  return anims;
}

export function usePulse(active: boolean) {
  const scale = useRef(new Animated.Value(1)).current;
  const pulseAnim = useRef<Animated.CompositeAnimation | null>(null);

  useEffect(() => {
    if (active) {
      pulseAnim.current = Animated.loop(
        Animated.sequence([
          Animated.timing(scale, {
            toValue: 1.3,
            duration: 800,
            easing: Easing.inOut(Easing.sine),
            useNativeDriver: true,
          }),
          Animated.timing(scale, {
            toValue: 1,
            duration: 800,
            easing: Easing.inOut(Easing.sine),
            useNativeDriver: true,
          }),
        ])
      );
      pulseAnim.current.start();
    } else {
      pulseAnim.current?.stop();
      scale.setValue(1);
    }
    return () => pulseAnim.current?.stop();
  }, [active]);

  return scale;
}

export function useShimmer() {
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const anim = Animated.loop(
      Animated.timing(shimmer, {
        toValue: 1,
        duration: 1200,
        easing: Easing.linear,
        useNativeDriver: false,
      })
    );
    anim.start();
    return () => anim.stop();
  }, []);

  return shimmer;
}

export function usePressScale(scale = 0.96) {
  const pressScale = useRef(new Animated.Value(1)).current;

  const onPressIn = () => {
    Animated.spring(pressScale, {
      toValue: scale,
      speed: 50,
      bounciness: 2,
      useNativeDriver: true,
    }).start();
  };

  const onPressOut = () => {
    Animated.spring(pressScale, {
      toValue: 1,
      speed: 50,
      bounciness: 4,
      useNativeDriver: true,
    }).start();
  };

  return { pressScale, onPressIn, onPressOut };
}

export function useCountUp(target: number, duration = 1000) {
  const current = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(current, {
      toValue: target,
      duration,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false,
    }).start();
  }, [target]);

  return current;
}

export function useGlow(intensity = 1) {
  const glow = useRef(new Animated.Value(0.5)).current;

  useEffect(() => {
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(glow, {
          toValue: intensity,
          duration: 1500,
          easing: Easing.inOut(Easing.sine),
          useNativeDriver: false,
        }),
        Animated.timing(glow, {
          toValue: 0.3,
          duration: 1500,
          easing: Easing.inOut(Easing.sine),
          useNativeDriver: false,
        }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, []);

  return glow;
}

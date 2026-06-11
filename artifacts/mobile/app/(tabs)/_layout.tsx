import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { Feather } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import React, { useEffect } from "react";
import { Platform, StyleSheet, View, Text } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  FadeInDown,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import colors from "@/constants/colors";

const C = colors.dark;

type FeatherName = React.ComponentProps<typeof Feather>["name"];

const TABS: { name: string; title: string; icon: FeatherName }[] = [
  { name: "index", title: "Dashboard", icon: "bar-chart-2" },
  { name: "trades", title: "Trades", icon: "list" },
  { name: "agents", title: "Agents", icon: "cpu" },
  { name: "news", title: "News", icon: "rss" },
  { name: "settings", title: "Settings", icon: "sliders" },
];

function TabIcon({ icon, label, focused }: { icon: FeatherName; label: string; focused: boolean }) {
  const scale = useSharedValue(focused ? 1 : 0.88);
  const bgOpacity = useSharedValue(focused ? 1 : 0);
  const bgWidth = useSharedValue(focused ? 48 : 36);
  const dotScale = useSharedValue(focused ? 1 : 0);
  const labelOpacity = useSharedValue(focused ? 1 : 0);
  const labelTranslateY = useSharedValue(focused ? 0 : 4);

  useEffect(() => {
    scale.value = withSpring(focused ? 1 : 0.88, { damping: 16, stiffness: 200 });
    bgOpacity.value = withTiming(focused ? 1 : 0, { duration: 200 });
    bgWidth.value = withSpring(focused ? 52 : 36, { damping: 18, stiffness: 220 });
    dotScale.value = withSpring(focused ? 1 : 0, { damping: 14, stiffness: 240 });
    labelOpacity.value = withTiming(focused ? 1 : 0.55, { duration: 200 });
    labelTranslateY.value = withSpring(focused ? 0 : 3, { damping: 16, stiffness: 200 });
  }, [focused]);

  const iconWrapStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const bgStyle = useAnimatedStyle(() => ({
    opacity: bgOpacity.value,
    width: bgWidth.value,
  }));

  const dotStyle = useAnimatedStyle(() => ({
    transform: [{ scale: dotScale.value }],
  }));

  const labelStyle = useAnimatedStyle(() => ({
    opacity: labelOpacity.value,
    transform: [{ translateY: labelTranslateY.value }],
  }));

  return (
    <View style={styles.tabItem}>
      <Animated.View style={[styles.iconWrap, iconWrapStyle]}>
        <Animated.View style={[styles.iconBg, bgStyle]} />
        <Feather name={icon} size={21} color={focused ? C.accentBright : C.tabInactive} />
      </Animated.View>
      <Animated.Text
        style={[
          styles.tabLabel,
          { color: focused ? C.accentBright : C.tabInactive },
          labelStyle,
        ]}
      >
        {label}
      </Animated.Text>
      <Animated.View style={[styles.dot, dotStyle]} />
    </View>
  );
}

export default function TabLayout() {
  const insets = useSafeAreaInsets();

  return (
    <Animated.View style={{ flex: 1 }} entering={FadeInDown.delay(80).springify().damping(20)}>
      <Tabs
        screenOptions={{
          headerShown: false,
          tabBarStyle: {
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 64 + insets.bottom,
            borderTopWidth: 0,
            backgroundColor: "transparent",
            elevation: 0,
          },
          tabBarBackground: () => (
            <View style={StyleSheet.absoluteFill}>
              <View
                style={[
                  StyleSheet.absoluteFill,
                  {
                    backgroundColor: C.tabBar,
                    borderTopWidth: 1,
                    borderTopColor: C.glassBorder,
                  },
                ]}
              />
              {Platform.OS === "ios" && (
                <BlurView intensity={60} tint="dark" style={StyleSheet.absoluteFill} />
              )}
            </View>
          ),
          tabBarShowLabel: false,
        }}
      >
        {TABS.map((tab) => (
          <Tabs.Screen
            key={tab.name}
            name={tab.name}
            options={{
              tabBarIcon: ({ focused }) => (
                <TabIcon icon={tab.icon} label={tab.title} focused={focused} />
              ),
              tabBarButton: (props) => {
                const { onPress, ...rest } = props as any;
                return (
                  <View
                    {...rest}
                    onStartShouldSetResponder={() => true}
                    onResponderGrant={() => {
                      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                      onPress?.();
                    }}
                    style={[props.style, { flex: 1 }]}
                  />
                );
              },
            }}
          />
        ))}
      </Tabs>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  tabItem: {
    alignItems: "center",
    flex: 1,
    paddingTop: 8,
    width: 60,
  },
  iconWrap: {
    position: "relative",
    marginBottom: 3,
    width: 36,
    height: 36,
    justifyContent: "center",
    alignItems: "center",
    borderRadius: 12,
  },
  iconBg: {
    position: "absolute",
    height: 36,
    borderRadius: 18,
    backgroundColor: C.accentLight,
    shadowColor: C.accentBright,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 12,
    alignSelf: "center",
  },
  tabLabel: {
    fontSize: 10,
    fontFamily: "Inter_500Medium",
    letterSpacing: 0.2,
  },
  dot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: C.accentBright,
    marginTop: 3,
    shadowColor: C.accentBright,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 6,
  },
});

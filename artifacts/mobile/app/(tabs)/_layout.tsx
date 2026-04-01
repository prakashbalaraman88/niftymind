import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { Feather } from "@expo/vector-icons";
import React, { useRef, useEffect } from "react";
import { Platform, StyleSheet, View, Text, Animated } from "react-native";
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
  const scale = useRef(new Animated.Value(focused ? 1 : 0.88)).current;
  const bgOpacity = useRef(new Animated.Value(focused ? 1 : 0)).current;
  const dotScale = useRef(new Animated.Value(focused ? 1 : 0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(scale, { toValue: focused ? 1 : 0.88, speed: 40, bounciness: 8, useNativeDriver: true }),
      Animated.timing(bgOpacity, { toValue: focused ? 1 : 0, duration: 200, useNativeDriver: true }),
      Animated.spring(dotScale, { toValue: focused ? 1 : 0, speed: 50, bounciness: 10, useNativeDriver: true }),
    ]).start();
  }, [focused]);

  return (
    <View style={styles.tabItem}>
      <Animated.View style={[styles.iconWrap, { transform: [{ scale }] }]}>
        <Animated.View style={[styles.iconBg, { opacity: bgOpacity }]} />
        <Feather name={icon} size={21} color={focused ? C.accentBright : C.tabInactive} />
      </Animated.View>
      <Text style={[styles.tabLabel, { color: focused ? C.accentBright : C.tabInactive }]}>
        {label}
      </Text>
      <Animated.View style={[styles.dot, { transform: [{ scale: dotScale }] }]} />
    </View>
  );
}

export default function TabLayout() {
  const insets = useSafeAreaInsets();

  return (
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
            <View style={[StyleSheet.absoluteFill, {
              backgroundColor: C.tabBar,
              borderTopWidth: 1,
              borderTopColor: C.glassBorder,
            }]} />
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
          }}
        />
      ))}
    </Tabs>
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
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderRadius: 12,
    backgroundColor: C.accentLight,
    shadowColor: C.accentBright,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 10,
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

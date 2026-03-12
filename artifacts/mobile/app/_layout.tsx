import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  useFonts,
} from "@expo-google-fonts/inter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import React, { useEffect, useRef } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { WebSocketProvider, useWebSocket } from "@/contexts/WebSocketContext";
import {
  registerForPushNotifications,
  fireTradeNotification,
  fireRiskNotification,
} from "@/lib/notifications";

SplashScreen.preventAutoHideAsync();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 5000,
    },
  },
});

function NotificationWatcher({ children }: { children: React.ReactNode }) {
  const { subscribe } = useWebSocket();
  const registeredRef = useRef(false);

  useEffect(() => {
    if (!registeredRef.current) {
      registeredRef.current = true;
      registerForPushNotifications();
    }
  }, []);

  useEffect(() => {
    const unsub1 = subscribe("trade_execution", (data: unknown) => {
      fireTradeNotification(data as Record<string, unknown>);
    });
    const unsub2 = subscribe("risk_alert", (data: unknown) => {
      fireRiskNotification(data as Record<string, unknown>);
    });
    return () => { unsub1(); unsub2(); };
  }, [subscribe]);

  return <>{children}</>;
}

function RootLayoutNav() {
  return (
    <Stack screenOptions={{ headerBackTitle: "Back" }}>
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
    </Stack>
  );
}

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });

  useEffect(() => {
    if (fontsLoaded || fontError) {
      SplashScreen.hideAsync();
    }
  }, [fontsLoaded, fontError]);

  if (!fontsLoaded && !fontError) return null;

  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <WebSocketProvider>
            <NotificationWatcher>
              <GestureHandlerRootView>
                <KeyboardProvider>
                  <RootLayoutNav />
                </KeyboardProvider>
              </GestureHandlerRootView>
            </NotificationWatcher>
          </WebSocketProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}

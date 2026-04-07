import React, { useEffect } from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import colors from "@/constants/colors";

const C = colors.dark;

/**
 * Handles the deep link redirect from Zerodha OAuth callback.
 * URL: niftymind://zerodha/callback?status=success&user_id=AB1234
 */
export default function ZerodhaCallbackScreen() {
  const params = useLocalSearchParams<{
    status?: string;
    user_id?: string;
    message?: string;
  }>();
  const router = useRouter();

  const isSuccess = params.status === "success";

  useEffect(() => {
    // Auto-navigate back to settings after a short delay
    const timer = setTimeout(() => {
      router.replace("/(tabs)/settings");
    }, 2500);
    return () => clearTimeout(timer);
  }, []);

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <View
          style={[
            styles.iconWrap,
            { backgroundColor: isSuccess ? C.greenDark : C.redDark },
          ]}
        >
          <Feather
            name={isSuccess ? "check-circle" : "x-circle"}
            size={40}
            color={isSuccess ? C.green : C.red}
          />
        </View>
        <Text style={styles.title}>
          {isSuccess ? "Zerodha Connected" : "Connection Failed"}
        </Text>
        <Text style={styles.subtitle}>
          {isSuccess
            ? `Logged in as ${params.user_id ?? "user"}. Token valid for today.`
            : params.message ?? "Something went wrong. Please try again."}
        </Text>
        <ActivityIndicator
          color={C.textTertiary}
          size="small"
          style={{ marginTop: 24 }}
        />
        <Text style={styles.redirectText}>Redirecting to settings...</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: C.bg,
    justifyContent: "center",
    alignItems: "center",
    padding: 30,
  },
  content: {
    alignItems: "center",
    maxWidth: 300,
  },
  iconWrap: {
    width: 80,
    height: 80,
    borderRadius: 24,
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 20,
  },
  title: {
    fontSize: 22,
    fontFamily: "Inter_700Bold",
    color: C.text,
    textAlign: "center",
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    fontFamily: "Inter_400Regular",
    color: C.textSecondary,
    textAlign: "center",
    lineHeight: 20,
  },
  redirectText: {
    fontSize: 12,
    fontFamily: "Inter_400Regular",
    color: C.textTertiary,
    marginTop: 8,
  },
});

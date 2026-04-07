import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Alert,
  Animated,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Feather } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import colors from "@/constants/colors";
import { useAuth } from "@/contexts/AuthContext";

const C = colors.dark;

export default function LoginScreen() {
  const insets = useSafeAreaInsets();
  const { signInWithGoogle, loading } = useAuth();
  const [pressing, setPressing] = useState(false);

  const handleGoogleSignIn = async () => {
    try {
      await signInWithGoogle();
    } catch (error: unknown) {
      const message =
        error instanceof Error ? error.message : "Something went wrong";
      Alert.alert("Sign In Failed", message);
    }
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top + 60 }]}>
      <LinearGradient
        colors={["rgba(124,58,237,0.15)", "transparent"]}
        style={styles.topGlow}
      />

      {/* Logo & Brand */}
      <View style={styles.brandSection}>
        <View style={styles.logoWrap}>
          <LinearGradient
            colors={C.gradient.accent}
            style={styles.logoGradient}
          >
            <Feather name="trending-up" size={36} color="#fff" />
          </LinearGradient>
        </View>
        <Text style={styles.appName}>NiftyMind</Text>
        <Text style={styles.tagline}>
          AI-Powered Options Trading
        </Text>
      </View>

      {/* Features */}
      <View style={styles.features}>
        <FeatureItem
          icon="cpu"
          title="12 AI Agents"
          description="Multi-agent consensus system analyzing markets in real-time"
        />
        <FeatureItem
          icon="shield"
          title="Risk Management"
          description="Automated stop-loss, drawdown limits, and VIX-based halts"
        />
        <FeatureItem
          icon="zap"
          title="Zerodha Integration"
          description="Direct order execution via Kite Connect API"
        />
      </View>

      {/* Sign In Button */}
      <View style={[styles.bottomSection, { paddingBottom: insets.bottom + 30 }]}>
        <Pressable
          onPress={handleGoogleSignIn}
          onPressIn={() => setPressing(true)}
          onPressOut={() => setPressing(false)}
          disabled={loading}
        >
          <View
            style={[
              styles.googleButton,
              pressing && styles.googleButtonPressed,
            ]}
          >
            {loading ? (
              <ActivityIndicator color={C.text} size="small" />
            ) : (
              <>
                <View style={styles.googleIconWrap}>
                  <Text style={styles.googleIcon}>G</Text>
                </View>
                <Text style={styles.googleButtonText}>
                  Continue with Google
                </Text>
              </>
            )}
          </View>
        </Pressable>

        <Text style={styles.disclaimer}>
          By continuing, you agree to our Terms of Service{"\n"}and Privacy
          Policy
        </Text>
      </View>
    </View>
  );
}

function FeatureItem({
  icon,
  title,
  description,
}: {
  icon: React.ComponentProps<typeof Feather>["name"];
  title: string;
  description: string;
}) {
  return (
    <View style={styles.featureRow}>
      <View style={styles.featureIconWrap}>
        <Feather name={icon} size={18} color={C.accentBright} />
      </View>
      <View style={styles.featureText}>
        <Text style={styles.featureTitle}>{title}</Text>
        <Text style={styles.featureDesc}>{description}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: C.bg,
    paddingHorizontal: 28,
  },
  topGlow: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: 300,
  },
  brandSection: {
    alignItems: "center",
    marginBottom: 48,
  },
  logoWrap: {
    marginBottom: 20,
  },
  logoGradient: {
    width: 80,
    height: 80,
    borderRadius: 24,
    justifyContent: "center",
    alignItems: "center",
    shadowColor: C.accentBright,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 20,
    elevation: 10,
  },
  appName: {
    fontSize: 32,
    fontFamily: "Inter_700Bold",
    color: C.text,
    letterSpacing: -0.5,
    marginBottom: 8,
  },
  tagline: {
    fontSize: 16,
    fontFamily: "Inter_400Regular",
    color: C.textSecondary,
    letterSpacing: 0.3,
  },
  features: {
    gap: 20,
    marginBottom: 48,
  },
  featureRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 14,
  },
  featureIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: C.accentLight,
    justifyContent: "center",
    alignItems: "center",
    marginTop: 2,
  },
  featureText: {
    flex: 1,
  },
  featureTitle: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: C.text,
    marginBottom: 3,
  },
  featureDesc: {
    fontSize: 13,
    fontFamily: "Inter_400Regular",
    color: C.textSecondary,
    lineHeight: 18,
  },
  bottomSection: {
    flex: 1,
    justifyContent: "flex-end",
  },
  googleButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: C.elevated,
    borderRadius: 16,
    paddingVertical: 16,
    paddingHorizontal: 24,
    gap: 12,
    borderWidth: 1,
    borderColor: C.cardBorder,
  },
  googleButtonPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.98 }],
  },
  googleIconWrap: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: "#fff",
    justifyContent: "center",
    alignItems: "center",
  },
  googleIcon: {
    fontSize: 14,
    fontFamily: "Inter_700Bold",
    color: "#4285F4",
  },
  googleButtonText: {
    fontSize: 16,
    fontFamily: "Inter_600SemiBold",
    color: C.text,
  },
  disclaimer: {
    fontSize: 11,
    fontFamily: "Inter_400Regular",
    color: C.textTertiary,
    textAlign: "center",
    marginTop: 16,
    lineHeight: 16,
  },
});

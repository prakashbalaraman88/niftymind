import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import { useRouter } from "expo-router";
import { supabase } from "@/lib/supabase";

/**
 * OAuth callback handler for web.
 * After Google redirects to http://localhost:8081/auth/callback#access_token=...
 * this page extracts the tokens and sets the Supabase session.
 */
export default function AuthCallback() {
  const router = useRouter();

  useEffect(() => {
    // detectSessionInUrl: true in supabase.ts handles this automatically on web,
    // but we also listen for the auth state change to navigate once signed in.
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if ((event === "SIGNED_IN" || event === "TOKEN_REFRESHED") && session) {
        router.replace("/(tabs)" as never);
      }
    });

    // Fallback: manually extract tokens from URL hash (covers PKCE & implicit flows)
    if (typeof window !== "undefined") {
      const hash = window.location.hash;
      const query = window.location.search;

      // Implicit flow: tokens in hash fragment
      if (hash) {
        const params = new URLSearchParams(hash.substring(1));
        const accessToken = params.get("access_token");
        const refreshToken = params.get("refresh_token");
        if (accessToken && refreshToken) {
          supabase.auth
            .setSession({ access_token: accessToken, refresh_token: refreshToken })
            .then(({ error }) => {
              if (!error) router.replace("/(tabs)" as never);
            });
        }
      }

      // PKCE flow: code in query params — supabase.auth handles exchange automatically
      // with detectSessionInUrl: true
    }

    return () => subscription.unsubscribe();
  }, []);

  return (
    <View
      style={{
        flex: 1,
        justifyContent: "center",
        alignItems: "center",
        backgroundColor: "#0a0a0f",
      }}
    >
      <ActivityIndicator size="large" color="#8b5cf6" />
    </View>
  );
}

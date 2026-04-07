import React, { useState, useEffect, useRef } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  Pressable,
  Alert,
  Switch,
  ActivityIndicator,
  Modal,
  Animated,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";
import Slider from "@react-native-community/slider";

import colors from "@/constants/colors";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { useAuth } from "@/contexts/AuthContext";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import type { Settings, ZerodhaStatus } from "@/types/api";

const C = colors.dark;
const INSTRUMENTS = ["NIFTY", "BANKNIFTY"];

export default function SettingsScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { connected, subscribe } = useWebSocket();
  const pageOpacity = useRef(new Animated.Value(0)).current;

  const { user, signOut } = useAuth();

  const { data: settings, isLoading, isError } = useQuery<Settings>({
    queryKey: ["settings"],
    queryFn: api.getSettings,
    refetchInterval: 60000,
    retry: false,
  });

  const { data: zerodhaStatus, refetch: refetchZerodha } = useQuery<ZerodhaStatus>({
    queryKey: ["zerodha-status"],
    queryFn: api.getZerodhaStatus,
    refetchInterval: 120000,
    retry: false,
  });

  useEffect(() => {
    Animated.timing(pageOpacity, { toValue: 1, duration: 500, useNativeDriver: true }).start();
  }, []);

  useEffect(() => {
    const unsub = subscribe("trade_execution", () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    });
    return unsub;
  }, [subscribe, queryClient]);

  const [capital, setCapital] = useState("");
  const [maxDailyLoss, setMaxDailyLoss] = useState("");
  const [maxTradeRisk, setMaxTradeRisk] = useState(2.0);
  const [maxPositions, setMaxPositions] = useState(5);
  const [selectedInstruments, setSelectedInstruments] = useState<string[]>(["NIFTY", "BANKNIFTY"]);
  const [showPinModal, setShowPinModal] = useState(false);
  const [pin, setPin] = useState("");

  useEffect(() => {
    if (settings) {
      setCapital(String(settings.capital));
      setMaxDailyLoss(String(settings.max_daily_loss));
      setMaxTradeRisk(settings.max_trade_risk_pct);
      setMaxPositions(settings.max_open_positions);
      if (settings.instruments?.length) setSelectedInstruments(settings.instruments);
    }
  }, [settings]);

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => api.updateSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    },
    onError: (err: Error) => {
      Alert.alert("Error", err.message);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    },
  });

  const isLive = settings?.trading_mode === "live";

  const handleModeToggle = () => {
    if (isLive) {
      mutation.mutate({ trading_mode: "paper" });
    } else {
      setShowPinModal(true);
      setPin("");
    }
  };

  const handlePinSubmit = () => {
    if (pin.length < 4) { Alert.alert("Invalid PIN", "Enter at least 4 digits."); return; }
    setShowPinModal(false);
    mutation.mutate({ trading_mode: "live", live_pin: pin });
  };

  const toggleInstrument = (instrument: string) => {
    setSelectedInstruments((prev) => {
      let next: string[];
      if (prev.includes(instrument)) {
        if (prev.length <= 1) return prev;
        next = prev.filter((i) => i !== instrument);
      } else {
        next = [...prev, instrument];
      }
      mutation.mutate({ instruments: next });
      return next;
    });
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
  };

  const handleSaveRisk = () => {
    const updates: Record<string, unknown> = {};
    const cap = parseFloat(capital);
    if (!isNaN(cap) && cap > 0 && cap !== settings?.capital) updates.capital = cap;
    const mdl = parseFloat(maxDailyLoss);
    if (!isNaN(mdl) && mdl > 0 && mdl !== settings?.max_daily_loss) updates.max_daily_loss = mdl;
    if (maxTradeRisk !== settings?.max_trade_risk_pct) updates.max_trade_risk_pct = maxTradeRisk;
    if (maxPositions !== settings?.max_open_positions) updates.max_open_positions = maxPositions;
    if (Object.keys(updates).length === 0) { Alert.alert("No Changes", "Nothing to update."); return; }
    mutation.mutate(updates);
  };

  const handleZerodhaLogin = async () => {
    try {
      const { login_url } = await api.getZerodhaLoginUrl();
      // Open Zerodha login in browser; callback redirects via deep link
      await WebBrowser.openBrowserAsync(login_url);
      // Refetch status after returning from browser
      setTimeout(() => refetchZerodha(), 2000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to open Zerodha login";
      Alert.alert("Zerodha Login Error", msg);
    }
  };

  const handleSignOut = () => {
    Alert.alert("Sign Out", "Are you sure you want to sign out?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Sign Out",
        style: "destructive",
        onPress: () => signOut(),
      },
    ]);
  };

  if (isLoading && !isError) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator color={C.accentBright} size="large" />
      </View>
    );
  }

  return (
    <>
      <Animated.View style={[{ flex: 1 }, { opacity: pageOpacity }]}>
        <ScrollView
          style={styles.container}
          contentContainerStyle={{ paddingTop: 12, paddingBottom: insets.bottom + 100 }}
          keyboardDismissMode="on-drag"
        >
          <Card style={styles.modeCard}>
            <LinearGradient
              colors={isLive ? ["rgba(255,59,92,0.12)", "transparent"] : ["rgba(124,58,237,0.08)", "transparent"]}
              style={StyleSheet.absoluteFill}
              pointerEvents="none"
            />
            <View style={styles.modeHeader}>
              <View style={styles.modeInfo}>
                <View style={[styles.modeIconWrap, { backgroundColor: isLive ? C.redDark : C.accentLight }]}>
                  <Feather name={isLive ? "zap" : "shield"} size={16} color={isLive ? C.red : C.accentBright} />
                </View>
                <View>
                  <Text style={styles.modeTitle}>Trading Mode</Text>
                  <StatusBadge label={isLive ? "LIVE" : "PAPER"} variant={isLive ? "live" : "paper"} size="medium" />
                </View>
              </View>
              <Switch
                value={!!isLive}
                onValueChange={handleModeToggle}
                trackColor={{ false: C.elevated, true: C.red }}
                thumbColor={isLive ? C.red : C.textSecondary}
                ios_backgroundColor={C.elevated}
              />
            </View>
            <Text style={styles.modeSubtitle}>
              {isLive
                ? "Real orders via Zerodha Kite. Be cautious."
                : "Trades are simulated. No real money at risk."}
            </Text>
          </Card>

          <Card style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>Instruments</Text>
            <Text style={styles.sectionSubtitle}>Select which indices to trade</Text>
            <View style={styles.instrumentRow}>
              {INSTRUMENTS.map((inst) => {
                const isSelected = selectedInstruments.includes(inst);
                return (
                  <Pressable key={inst} onPress={() => toggleInstrument(inst)} style={{ flex: 1 }}>
                    {isSelected ? (
                      <LinearGradient
                        colors={C.gradient.accent}
                        start={{ x: 0, y: 0 }}
                        end={{ x: 1, y: 0 }}
                        style={styles.instrumentChipActive}
                      >
                        <Feather name="check-circle" size={15} color="#fff" />
                        <Text style={styles.instrumentTextActive}>{inst}</Text>
                      </LinearGradient>
                    ) : (
                      <View style={styles.instrumentChip}>
                        <Feather name="circle" size={15} color={C.textTertiary} />
                        <Text style={styles.instrumentText}>{inst}</Text>
                      </View>
                    )}
                  </Pressable>
                );
              })}
            </View>
          </Card>

          <Card style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>Connection</Text>
            <View style={styles.settingRow}>
              <View style={[styles.settingIcon, { backgroundColor: connected ? C.greenDark : C.redDark }]}>
                <Feather name="wifi" size={13} color={connected ? C.green : C.red} />
              </View>
              <Text style={styles.settingLabel}>WebSocket</Text>
              <Text style={[styles.settingValue, { color: connected ? C.green : C.red }]}>
                {connected ? "Connected" : "Disconnected"}
              </Text>
            </View>
          </Card>

          {/* Zerodha Broker Connection */}
          <Card style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>Zerodha Broker</Text>
            <Text style={styles.sectionSubtitle}>
              Connect your Zerodha account for live trading
            </Text>
            <View style={styles.settingRow}>
              <View
                style={[
                  styles.settingIcon,
                  {
                    backgroundColor: zerodhaStatus?.authenticated
                      ? C.greenDark
                      : C.redDark,
                  },
                ]}
              >
                <Feather
                  name={zerodhaStatus?.authenticated ? "check-circle" : "link"}
                  size={13}
                  color={zerodhaStatus?.authenticated ? C.green : C.red}
                />
              </View>
              <Text style={styles.settingLabel}>
                {zerodhaStatus?.authenticated
                  ? `${zerodhaStatus.user_name ?? zerodhaStatus.user_id}`
                  : "Not connected"}
              </Text>
              {zerodhaStatus?.authenticated ? (
                <StatusBadge label="ACTIVE" variant="live" size="medium" />
              ) : (
                <Pressable onPress={handleZerodhaLogin}>
                  <LinearGradient
                    colors={C.gradient.accent}
                    start={{ x: 0, y: 0 }}
                    end={{ x: 1, y: 0 }}
                    style={styles.connectBtn}
                  >
                    <Text style={styles.connectBtnText}>Connect</Text>
                  </LinearGradient>
                </Pressable>
              )}
            </View>
            {zerodhaStatus?.authenticated && (
              <Text style={styles.zerodhaNote}>
                Token expires daily at 6:00 AM. Re-login required each trading day.
              </Text>
            )}
          </Card>

          <Card style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>Capital & Risk</Text>

            <DarkInput label="Capital" prefix="₹" value={capital} onChangeText={setCapital} keyboardType="numeric" />
            <DarkInput label="Max Daily Loss" prefix="₹" value={maxDailyLoss} onChangeText={setMaxDailyLoss} keyboardType="numeric" />

            <View style={styles.sliderRow}>
              <View style={styles.sliderHeader}>
                <Text style={styles.inputLabel}>Max Trade Risk</Text>
                <Text style={styles.sliderValue}>{maxTradeRisk.toFixed(1)}%</Text>
              </View>
              <Slider
                style={styles.slider}
                minimumValue={0.5}
                maximumValue={10}
                step={0.5}
                value={maxTradeRisk}
                onValueChange={setMaxTradeRisk}
                minimumTrackTintColor={C.accentBright}
                maximumTrackTintColor={C.elevated}
                thumbTintColor={C.accentBright}
              />
            </View>

            <View style={styles.sliderRow}>
              <View style={styles.sliderHeader}>
                <Text style={styles.inputLabel}>Max Open Positions</Text>
                <Text style={styles.sliderValue}>{maxPositions}</Text>
              </View>
              <Slider
                style={styles.slider}
                minimumValue={1}
                maximumValue={20}
                step={1}
                value={maxPositions}
                onValueChange={setMaxPositions}
                minimumTrackTintColor={C.accentBright}
                maximumTrackTintColor={C.elevated}
                thumbTintColor={C.accentBright}
              />
            </View>

            <Pressable onPress={handleSaveRisk} disabled={mutation.isPending}>
              {({ pressed }) => (
                <LinearGradient
                  colors={C.gradient.accent}
                  start={{ x: 0, y: 0 }}
                  end={{ x: 1, y: 0 }}
                  style={[styles.saveButton, (pressed || mutation.isPending) && styles.saveButtonPressed]}
                >
                  {mutation.isPending ? (
                    <ActivityIndicator color="#fff" size="small" />
                  ) : (
                    <Text style={styles.saveButtonText}>Save Changes</Text>
                  )}
                </LinearGradient>
              )}
            </Pressable>
          </Card>

          <Card style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>System Info</Text>
            <SettingRow label="VIX Halt Threshold" value={String(settings?.vix_halt_threshold ?? 25)} />
            <SettingRow
              label="Consensus Threshold"
              value={`${((settings?.consensus_threshold ?? 0.6) * 100).toFixed(0)}%`}
            />
          </Card>

          {/* Account */}
          <Card style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>Account</Text>
            <View style={styles.settingRow}>
              <View style={[styles.settingIcon, { backgroundColor: C.accentLight }]}>
                <Feather name="user" size={13} color={C.accentBright} />
              </View>
              <Text style={styles.settingLabel}>{user?.email ?? "Unknown"}</Text>
            </View>
            <Pressable onPress={handleSignOut} style={styles.signOutBtn}>
              <Feather name="log-out" size={16} color={C.red} />
              <Text style={styles.signOutText}>Sign Out</Text>
            </Pressable>
          </Card>
        </ScrollView>
      </Animated.View>

      <Modal visible={showPinModal} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalIconWrap}>
              <Feather name="zap" size={28} color={C.red} />
            </View>
            <Text style={styles.modalTitle}>Enable Live Trading</Text>
            <Text style={styles.modalSubtitle}>
              Real orders will be placed. Enter your PIN to confirm.
            </Text>
            <View style={styles.pinInputWrap}>
              <TextInput
                style={styles.pinInput}
                value={pin}
                onChangeText={setPin}
                keyboardType="number-pad"
                secureTextEntry
                maxLength={8}
                placeholder="• • • •"
                placeholderTextColor={C.textTertiary}
                autoFocus
              />
            </View>
            <View style={styles.modalButtons}>
              <Pressable onPress={() => setShowPinModal(false)} style={styles.modalBtnCancel}>
                <Text style={styles.modalBtnCancelText}>Cancel</Text>
              </Pressable>
              <Pressable onPress={handlePinSubmit} style={{ flex: 1 }}>
                <LinearGradient
                  colors={C.gradient.loss}
                  start={{ x: 0, y: 0 }}
                  end={{ x: 1, y: 0 }}
                  style={styles.modalBtnConfirm}
                >
                  <Text style={styles.modalBtnConfirmText}>Confirm</Text>
                </LinearGradient>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

function DarkInput({
  label,
  value,
  onChangeText,
  prefix,
  suffix,
  keyboardType = "default",
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  prefix?: string;
  suffix?: string;
  keyboardType?: "default" | "numeric" | "decimal-pad" | "number-pad";
}) {
  return (
    <View style={styles.inputRow}>
      <Text style={styles.inputLabel}>{label}</Text>
      <View style={styles.inputWrap}>
        {!!prefix && <Text style={styles.inputAffix}>{prefix}</Text>}
        <TextInput
          style={styles.input}
          value={value}
          onChangeText={onChangeText}
          keyboardType={keyboardType}
          returnKeyType="done"
          placeholderTextColor={C.textTertiary}
        />
        {!!suffix && <Text style={styles.inputAffix}>{suffix}</Text>}
      </View>
    </View>
  );
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.settingRow}>
      <Text style={styles.settingLabel}>{label}</Text>
      <Text style={styles.settingValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  loadingContainer: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: C.bg },
  modeCard: { marginHorizontal: 20, marginBottom: 10, overflow: "hidden" },
  modeHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  modeInfo: { flexDirection: "row", alignItems: "center", gap: 12 },
  modeIconWrap: { width: 40, height: 40, borderRadius: 12, justifyContent: "center", alignItems: "center" },
  modeTitle: { fontSize: 14, fontFamily: "Inter_600SemiBold", color: C.text, marginBottom: 4 },
  modeSubtitle: { fontSize: 13, fontFamily: "Inter_400Regular", color: C.textSecondary, lineHeight: 18 },
  sectionCard: { marginHorizontal: 20, marginBottom: 10 },
  sectionTitle: { fontSize: 15, fontFamily: "Inter_600SemiBold", color: C.text, marginBottom: 4 },
  sectionSubtitle: { fontSize: 12, fontFamily: "Inter_400Regular", color: C.textSecondary, marginBottom: 12 },
  instrumentRow: { flexDirection: "row", gap: 10 },
  instrumentChip: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 12, borderRadius: 14, borderWidth: 1.5, borderColor: C.cardBorder, backgroundColor: C.elevated,
  },
  instrumentChipActive: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 12, borderRadius: 14,
  },
  instrumentText: { fontSize: 14, fontFamily: "Inter_600SemiBold", color: C.textSecondary },
  instrumentTextActive: { fontSize: 14, fontFamily: "Inter_600SemiBold", color: "#fff" },
  settingRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, gap: 10 },
  settingIcon: { width: 28, height: 28, borderRadius: 8, justifyContent: "center", alignItems: "center" },
  settingLabel: { fontSize: 14, fontFamily: "Inter_400Regular", color: C.textSecondary, flex: 1 },
  settingValue: { fontSize: 14, fontFamily: "Inter_500Medium", color: C.text },
  inputRow: { marginBottom: 14 },
  inputLabel: { fontSize: 12, fontFamily: "Inter_500Medium", color: C.textTertiary, marginBottom: 6, letterSpacing: 0.3 },
  inputWrap: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: C.elevated, borderRadius: 12, paddingHorizontal: 14,
    borderWidth: 1, borderColor: C.cardBorder,
  },
  inputAffix: { fontSize: 15, fontFamily: "Inter_500Medium", color: C.textSecondary },
  input: { flex: 1, fontSize: 15, fontFamily: "Inter_500Medium", color: C.text, paddingVertical: 12, paddingHorizontal: 4 },
  sliderRow: { marginBottom: 16 },
  sliderHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  sliderValue: { fontSize: 15, fontFamily: "Inter_700Bold", color: C.accentBright },
  slider: { width: "100%", height: 36 },
  saveButton: { borderRadius: 14, paddingVertical: 15, alignItems: "center", marginTop: 4 },
  saveButtonPressed: { opacity: 0.8 },
  saveButtonText: { fontSize: 15, fontFamily: "Inter_600SemiBold", color: "#fff" },
  modalOverlay: {
    flex: 1, backgroundColor: C.overlay,
    justifyContent: "center", alignItems: "center", padding: 30,
  },
  modalContent: {
    backgroundColor: C.card, borderRadius: 28, padding: 28,
    width: "100%", maxWidth: 340, borderWidth: 1, borderColor: C.cardBorder, alignItems: "center",
  },
  modalIconWrap: {
    width: 60, height: 60, borderRadius: 20, backgroundColor: C.redDark,
    justifyContent: "center", alignItems: "center", marginBottom: 16,
  },
  modalTitle: { fontSize: 20, fontFamily: "Inter_700Bold", color: C.text, textAlign: "center", marginBottom: 8 },
  modalSubtitle: { fontSize: 13, fontFamily: "Inter_400Regular", color: C.textSecondary, textAlign: "center", lineHeight: 20, marginBottom: 24 },
  pinInputWrap: { width: "100%", marginBottom: 24 },
  pinInput: {
    backgroundColor: C.elevated, borderRadius: 14, fontSize: 28, fontFamily: "Inter_700Bold",
    color: C.text, textAlign: "center", paddingVertical: 14, letterSpacing: 10,
    borderWidth: 1, borderColor: C.cardBorder,
  },
  modalButtons: { flexDirection: "row", gap: 12, width: "100%" },
  modalBtnCancel: {
    flex: 1, borderRadius: 14, paddingVertical: 14, alignItems: "center",
    backgroundColor: C.elevated, borderWidth: 1, borderColor: C.cardBorder,
  },
  modalBtnCancelText: { fontSize: 15, fontFamily: "Inter_500Medium", color: C.textSecondary },
  modalBtnConfirm: { borderRadius: 14, paddingVertical: 14, alignItems: "center" },
  modalBtnConfirmText: { fontSize: 15, fontFamily: "Inter_600SemiBold", color: "#fff" },
  connectBtn: { borderRadius: 10, paddingVertical: 8, paddingHorizontal: 16 },
  connectBtnText: { fontSize: 13, fontFamily: "Inter_600SemiBold", color: "#fff" },
  zerodhaNote: { fontSize: 11, fontFamily: "Inter_400Regular", color: C.textTertiary, marginTop: 8, lineHeight: 16 },
  signOutBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 14,
    marginTop: 8,
    borderRadius: 14,
    backgroundColor: C.redDark,
    borderWidth: 1,
    borderColor: "rgba(255,59,92,0.2)",
  },
  signOutText: { fontSize: 15, fontFamily: "Inter_600SemiBold", color: C.red },
});

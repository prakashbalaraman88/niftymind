import React, { useState, useEffect } from "react";
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
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import Slider from "@react-native-community/slider";

import colors from "@/constants/colors";
import { api } from "@/lib/api";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import type { Settings } from "@/types/api";

const INSTRUMENTS = ["NIFTY", "BANKNIFTY"];

export default function SettingsScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { connected, subscribe } = useWebSocket();

  const { data: settings, isLoading, isError } = useQuery<Settings>({
    queryKey: ["settings"],
    queryFn: api.getSettings,
    refetchInterval: 60000,
    retry: false,
  });

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
      if (settings.instruments?.length) {
        setSelectedInstruments(settings.instruments);
      }
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
    if (pin.length < 4) {
      Alert.alert("Invalid PIN", "Please enter at least 4 digits.");
      return;
    }
    setShowPinModal(false);
    mutation.mutate({ trading_mode: "live", live_pin: pin });
  };

  const toggleInstrument = (instrument: string) => {
    setSelectedInstruments((prev) => {
      if (prev.includes(instrument)) {
        if (prev.length <= 1) return prev;
        return prev.filter((i) => i !== instrument);
      }
      return [...prev, instrument];
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

    if (Object.keys(updates).length === 0) {
      Alert.alert("No Changes", "Nothing to update.");
      return;
    }
    mutation.mutate(updates);
  };

  if (isLoading && !isError) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator color={colors.light.tint} size="large" />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={{ paddingBottom: insets.bottom + 100 }}
      contentInsetAdjustmentBehavior="automatic"
      keyboardDismissMode="on-drag"
    >
      <Card style={styles.modeCard}>
        <View style={styles.modeHeader}>
          <View style={styles.modeInfo}>
            <Text style={styles.modeTitle}>Trading Mode</Text>
            <StatusBadge
              label={isLive ? "LIVE" : "PAPER"}
              variant={isLive ? "live" : "paper"}
              size="medium"
            />
          </View>
          <Switch
            value={!!isLive}
            onValueChange={handleModeToggle}
            trackColor={{ false: colors.light.border, true: colors.light.red }}
            thumbColor="#fff"
          />
        </View>
        <Text style={styles.modeSubtitle}>
          {isLive
            ? "Live mode: Real orders will be placed via Zerodha Kite."
            : "Paper mode: Trades are simulated, no real orders placed."}
        </Text>
      </Card>

      <Card style={styles.sectionCard}>
        <Text style={styles.sectionTitle}>Instruments</Text>
        <Text style={styles.sectionSubtitle}>Select which indices to trade</Text>
        <View style={styles.instrumentRow}>
          {INSTRUMENTS.map((inst) => {
            const isSelected = selectedInstruments.includes(inst);
            return (
              <Pressable
                key={inst}
                onPress={() => toggleInstrument(inst)}
                style={[styles.instrumentChip, isSelected && styles.instrumentChipActive]}
              >
                <Feather
                  name={isSelected ? "check-circle" : "circle"}
                  size={16}
                  color={isSelected ? colors.light.tint : colors.light.textTertiary}
                />
                <Text style={[styles.instrumentText, isSelected && styles.instrumentTextActive]}>
                  {inst}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </Card>

      <Card style={styles.sectionCard}>
        <Text style={styles.sectionTitle}>Connection</Text>
        <View style={styles.settingRow}>
          <Feather name="wifi" size={16} color={connected ? colors.light.green : colors.light.red} />
          <Text style={styles.settingLabel}>WebSocket</Text>
          <Text style={[styles.settingValue, { color: connected ? colors.light.green : colors.light.red }]}>
            {connected ? "Connected" : "Disconnected"}
          </Text>
        </View>
      </Card>

      <Card style={styles.sectionCard}>
        <Text style={styles.sectionTitle}>Capital & Risk</Text>

        <SettingInput
          label="Capital"
          prefix={"\u20B9"}
          value={capital}
          onChangeText={setCapital}
          keyboardType="numeric"
        />
        <SettingInput
          label="Max Daily Loss"
          prefix={"\u20B9"}
          value={maxDailyLoss}
          onChangeText={setMaxDailyLoss}
          keyboardType="numeric"
        />

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
            minimumTrackTintColor={colors.light.tint}
            maximumTrackTintColor={colors.light.border}
            thumbTintColor={colors.light.tint}
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
            minimumTrackTintColor={colors.light.tint}
            maximumTrackTintColor={colors.light.border}
            thumbTintColor={colors.light.tint}
          />
        </View>

        <Pressable
          onPress={handleSaveRisk}
          disabled={mutation.isPending}
          style={({ pressed }) => [
            styles.saveButton,
            pressed && styles.saveButtonPressed,
            mutation.isPending && styles.saveButtonDisabled,
          ]}
        >
          {mutation.isPending ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Text style={styles.saveButtonText}>Save Changes</Text>
          )}
        </Pressable>
      </Card>

      <Card style={styles.sectionCard}>
        <Text style={styles.sectionTitle}>System Info</Text>
        <View style={styles.settingRow}>
          <Text style={styles.settingLabel}>VIX Halt Threshold</Text>
          <Text style={styles.settingValue}>{settings?.vix_halt_threshold ?? 25}</Text>
        </View>
        <View style={styles.settingRow}>
          <Text style={styles.settingLabel}>Consensus Threshold</Text>
          <Text style={styles.settingValue}>{((settings?.consensus_threshold ?? 0.6) * 100).toFixed(0)}%</Text>
        </View>
      </Card>

      <Modal visible={showPinModal} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Enter Live Trading PIN</Text>
            <Text style={styles.modalSubtitle}>
              This will enable real order placement. Enter your PIN to confirm.
            </Text>
            <TextInput
              style={styles.pinInput}
              value={pin}
              onChangeText={setPin}
              keyboardType="number-pad"
              secureTextEntry
              maxLength={8}
              placeholder="PIN"
              placeholderTextColor={colors.light.textTertiary}
              autoFocus
            />
            <View style={styles.modalButtons}>
              <Pressable
                onPress={() => setShowPinModal(false)}
                style={({ pressed }) => [styles.modalBtn, styles.modalBtnCancel, pressed && { opacity: 0.8 }]}
              >
                <Text style={styles.modalBtnCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={handlePinSubmit}
                style={({ pressed }) => [styles.modalBtn, styles.modalBtnConfirm, pressed && { opacity: 0.8 }]}
              >
                <Text style={styles.modalBtnConfirmText}>Confirm</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

function SettingInput({
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
        />
        {!!suffix && <Text style={styles.inputAffix}>{suffix}</Text>}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.light.background,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: colors.light.background,
  },
  modeCard: {
    marginHorizontal: 20,
    marginTop: 12,
    marginBottom: 10,
  },
  modeHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  modeInfo: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  modeTitle: {
    fontSize: 16,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
  },
  modeSubtitle: {
    fontSize: 13,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
    lineHeight: 18,
  },
  sectionCard: {
    marginHorizontal: 20,
    marginBottom: 10,
  },
  sectionTitle: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
    marginBottom: 4,
  },
  sectionSubtitle: {
    fontSize: 12,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
    marginBottom: 12,
  },
  instrumentRow: {
    flexDirection: "row",
    gap: 10,
  },
  instrumentChip: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: colors.light.background,
    borderWidth: 1.5,
    borderColor: colors.light.border,
  },
  instrumentChipActive: {
    borderColor: colors.light.tint,
    backgroundColor: colors.light.tintLight,
  },
  instrumentText: {
    fontSize: 14,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.textSecondary,
  },
  instrumentTextActive: {
    color: colors.light.tint,
  },
  settingRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 8,
    gap: 8,
  },
  settingLabel: {
    fontSize: 14,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
    flex: 1,
  },
  settingValue: {
    fontSize: 14,
    fontFamily: "Inter_500Medium",
    color: colors.light.text,
  },
  inputRow: {
    marginBottom: 14,
  },
  inputLabel: {
    fontSize: 12,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
    marginBottom: 6,
  },
  inputWrap: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.light.background,
    borderRadius: 10,
    paddingHorizontal: 12,
  },
  inputAffix: {
    fontSize: 14,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
  },
  input: {
    flex: 1,
    fontSize: 15,
    fontFamily: "Inter_500Medium",
    color: colors.light.text,
    paddingVertical: 10,
    paddingHorizontal: 4,
  },
  sliderRow: {
    marginBottom: 16,
  },
  sliderHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  sliderValue: {
    fontSize: 14,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.tint,
  },
  slider: {
    width: "100%",
    height: 36,
  },
  saveButton: {
    backgroundColor: colors.light.tint,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  saveButtonPressed: {
    opacity: 0.9,
    transform: [{ scale: 0.98 }],
  },
  saveButtonDisabled: {
    opacity: 0.6,
  },
  saveButtonText: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: "#fff",
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: colors.light.overlay,
    justifyContent: "center",
    alignItems: "center",
    padding: 30,
  },
  modalContent: {
    backgroundColor: colors.light.surface,
    borderRadius: 20,
    padding: 24,
    width: "100%",
    maxWidth: 340,
  },
  modalTitle: {
    fontSize: 18,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
    textAlign: "center",
    marginBottom: 8,
  },
  modalSubtitle: {
    fontSize: 13,
    fontFamily: "Inter_400Regular",
    color: colors.light.textSecondary,
    textAlign: "center",
    lineHeight: 18,
    marginBottom: 20,
  },
  pinInput: {
    backgroundColor: colors.light.background,
    borderRadius: 12,
    fontSize: 24,
    fontFamily: "Inter_600SemiBold",
    color: colors.light.text,
    textAlign: "center",
    paddingVertical: 14,
    letterSpacing: 8,
    marginBottom: 20,
  },
  modalButtons: {
    flexDirection: "row",
    gap: 12,
  },
  modalBtn: {
    flex: 1,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
  },
  modalBtnCancel: {
    backgroundColor: colors.light.background,
  },
  modalBtnCancelText: {
    fontSize: 15,
    fontFamily: "Inter_500Medium",
    color: colors.light.textSecondary,
  },
  modalBtnConfirm: {
    backgroundColor: colors.light.red,
  },
  modalBtnConfirmText: {
    fontSize: 15,
    fontFamily: "Inter_600SemiBold",
    color: "#fff",
  },
});

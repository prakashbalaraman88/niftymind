import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Platform } from "react-native";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

export async function registerForPushNotifications(): Promise<string | null> {
  if (!Device.isDevice) {
    return null;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== "granted") {
    return null;
  }

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("trades", {
      name: "Trade Alerts",
      importance: Notifications.AndroidImportance.HIGH,
      sound: "default",
      vibrationPattern: [0, 250, 250, 250],
    });
    await Notifications.setNotificationChannelAsync("risk", {
      name: "Risk Alerts",
      importance: Notifications.AndroidImportance.MAX,
      sound: "default",
      vibrationPattern: [0, 500, 200, 500],
    });
  }

  try {
    const token = (await Notifications.getExpoPushTokenAsync()).data;
    return token;
  } catch {
    return null;
  }
}

export async function fireTradeNotification(data: Record<string, unknown>) {
  const action = (data.action as string) || "executed";
  const symbol = (data.symbol as string) || "Unknown";
  const direction = (data.direction as string) || "";
  const price = data.entry_price || data.exit_price || data.price || 0;
  const pnl = data.pnl as number | undefined;

  let title: string;
  let body: string;

  if (action === "EXIT_ORDER" || action === "EXIT" || data.exit_price) {
    const pnlStr = pnl != null ? ` | P&L: \u20B9${pnl.toLocaleString("en-IN")}` : "";
    title = `\u{1F534} Position Closed: ${symbol}`;
    body = `Exit @ \u20B9${price}${pnlStr}`;
  } else {
    title = `\u{1F7E2} Trade Executed: ${symbol}`;
    body = `${direction} @ \u20B9${price}`;
  }

  await Notifications.scheduleNotificationAsync({
    content: {
      title,
      body,
      sound: "default",
      ...(Platform.OS === "android" ? { channelId: "trades" } : {}),
    },
    trigger: null,
  });
}

export async function fireRiskNotification(data: Record<string, unknown>) {
  const event = (data.event as string) || (data.message as string) || "Risk alert";
  const detail = (data.detail as string) || (data.reasoning as string) || "";

  await Notifications.scheduleNotificationAsync({
    content: {
      title: "\u26A0\uFE0F Risk Alert",
      body: detail ? `${event}: ${detail}` : event,
      sound: "default",
      ...(Platform.OS === "android" ? { channelId: "risk" } : {}),
    },
    trigger: null,
  });
}

import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Platform } from "react-native";
import Constants from "expo-constants";
import { api } from "./api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

async function getFcmDeviceToken(): Promise<string | null> {
  try {
    const tokenData = await Notifications.getDevicePushTokenAsync();
    return tokenData.data as string;
  } catch {
    return null;
  }
}

async function getExpoPushToken(): Promise<string | null> {
  try {
    const projectId = Constants.expoConfig?.extra?.eas?.projectId;
    const tokenData = await Notifications.getExpoPushTokenAsync({
      projectId: projectId || undefined,
    });
    return tokenData.data;
  } catch {
    return null;
  }
}

export async function registerForPushNotifications(): Promise<{
  expoPushToken: string | null;
  fcmToken: string | null;
}> {
  const result = { expoPushToken: null as string | null, fcmToken: null as string | null };

  if (!Device.isDevice) {
    return result;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== "granted") {
    return result;
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

  result.fcmToken = await getFcmDeviceToken();
  result.expoPushToken = await getExpoPushToken();

  const tokenToRegister = result.fcmToken || result.expoPushToken;
  if (tokenToRegister) {
    try {
      await api.registerPushToken(tokenToRegister);
    } catch {
      // Backend may not support push token registration yet
    }
  }

  return result;
}

export function addNotificationReceivedListener(
  handler: (notification: Notifications.Notification) => void
): Notifications.EventSubscription {
  return Notifications.addNotificationReceivedListener(handler);
}

export function addNotificationResponseListener(
  handler: (response: Notifications.NotificationResponse) => void
): Notifications.EventSubscription {
  return Notifications.addNotificationResponseReceivedListener(handler);
}

export async function fireTradeNotification(data: Record<string, unknown>) {
  if (Platform.OS === "web") return; // Notifications not supported on web

  const action = (data.action as string) || "executed";
  const symbol = (data.symbol as string) || "Unknown";
  const direction = (data.direction as string) || "";
  const price = data.entry_price || data.exit_price || data.price || 0;
  const pnl = data.pnl as number | undefined;

  let title: string;
  let body: string;

  if (action === "EXIT_ORDER" || action === "EXIT" || data.exit_price) {
    const pnlStr = pnl != null ? ` | P&L: \u20B9${pnl.toLocaleString("en-IN")}` : "";
    title = "Position Closed: " + symbol;
    body = `Exit @ \u20B9${price}${pnlStr}`;
  } else {
    title = "Trade Executed: " + symbol;
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
  if (Platform.OS === "web") return; // Notifications not supported on web

  const event = (data.event as string) || (data.message as string) || "Risk alert";
  const detail = (data.detail as string) || (data.reasoning as string) || "";

  await Notifications.scheduleNotificationAsync({
    content: {
      title: "Risk Alert",
      body: detail ? `${event}: ${detail}` : event,
      sound: "default",
      ...(Platform.OS === "android" ? { channelId: "risk" } : {}),
    },
    trigger: null,
  });
}

const colors = {
  dark: {
    bg: "#070709",
    bgDeep: "#000000",
    surface: "#0F1014",
    elevated: "#16181E",
    card: "#1A1C24",
    cardBorder: "rgba(255,255,255,0.07)",
    glassBorder: "rgba(255,255,255,0.10)",

    text: "#FFFFFF",
    textSecondary: "rgba(255,255,255,0.55)",
    textTertiary: "rgba(255,255,255,0.30)",
    textQuaternary: "rgba(255,255,255,0.15)",

    accent: "#7C3AED",
    accentBright: "#8B5CF6",
    accentGlow: "rgba(124,58,237,0.4)",
    accentLight: "rgba(124,58,237,0.15)",

    green: "#10F0A0",
    greenDim: "#22D47A",
    greenGlow: "rgba(16,240,160,0.25)",
    greenDark: "rgba(16,240,160,0.12)",

    red: "#FF3B5C",
    redDim: "#FF4560",
    redGlow: "rgba(255,59,92,0.25)",
    redDark: "rgba(255,59,92,0.12)",

    gold: "#FFB800",
    goldGlow: "rgba(255,184,0,0.25)",
    goldDark: "rgba(255,184,0,0.12)",

    border: "rgba(255,255,255,0.07)",
    separator: "rgba(255,255,255,0.05)",
    overlay: "rgba(0,0,0,0.75)",

    tabActive: "#8B5CF6",
    tabInactive: "rgba(255,255,255,0.30)",
    tabBar: "rgba(7,7,9,0.92)",

    gradient: {
      accent: ["#7C3AED", "#2563EB"] as [string, string],
      profit: ["#10F0A0", "#22D47A"] as [string, string],
      loss: ["#FF3B5C", "#FF6B81"] as [string, string],
      card: ["#1A1C24", "#13151C"] as [string, string],
      surface: ["rgba(26,28,36,0.9)", "rgba(13,15,20,0.95)"] as [string, string],
      gold: ["#FFB800", "#FF7C00"] as [string, string],
    },

    shimmer1: "#1A1C24",
    shimmer2: "#22252F",
    shimmer3: "#1A1C24",

    cardShadow: "rgba(0,0,0,0.6)",
    glowPurple: "rgba(124,58,237,0.5)",
  },

  light: {
    text: "#0A0E17",
    textSecondary: "#5A6478",
    textTertiary: "#8892A6",
    background: "#F0F2F5",
    surface: "#FFFFFF",
    border: "#E2E6ED",
    tint: "#2563EB",
    tintLight: "#EFF4FF",
    green: "#10B981",
    greenLight: "#ECFDF5",
    red: "#EF4444",
    redLight: "#FEF2F2",
    yellow: "#F59E0B",
    yellowLight: "#FFFBEB",
    orange: "#F97316",
    tabIconDefault: "#8892A6",
    tabIconSelected: "#2563EB",
    cardShadow: "rgba(0, 0, 0, 0.06)",
    overlay: "rgba(0, 0, 0, 0.4)",
  },
};

export default colors;

import type { ComponentProps } from "react";
import type { Feather } from "@expo/vector-icons";

type FeatherIcon = ComponentProps<typeof Feather>["name"];

interface AgentInfo {
  name: string;
  shortName: string;
  icon: FeatherIcon;
}

export const AGENT_INFO: Record<string, AgentInfo> = {
  agent_1_options_chain: { name: "Options Chain", shortName: "OI", icon: "layers" },
  agent_2_order_flow: { name: "Order Flow", shortName: "Flow", icon: "git-branch" },
  agent_3_volume_profile: { name: "Volume Profile", shortName: "Vol", icon: "activity" },
  agent_4_technical: { name: "Technical Analysis", shortName: "Trend", icon: "trending-up" },
  agent_5_sentiment: { name: "Market Sentiment", shortName: "Mood", icon: "eye" },
  agent_6_news: { name: "News & Events", shortName: "News", icon: "rss" },
  agent_7_macro: { name: "Global Macro", shortName: "Macro", icon: "globe" },
  agent_8_scalping: { name: "Scalping", shortName: "Scalp", icon: "zap" },
  agent_9_intraday: { name: "Intraday", shortName: "Swing", icon: "bar-chart-2" },
  agent_10_btst: { name: "BTST", shortName: "Position", icon: "clock" },
  agent_11_risk: { name: "Risk Manager", shortName: "Risk", icon: "shield" },
  agent_12_consensus: { name: "Consensus", shortName: "Consensus", icon: "users" },
};

export const AGENT_IDS = Object.keys(AGENT_INFO);

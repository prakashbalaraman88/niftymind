import type { ComponentProps } from "react";
import type { Feather } from "@expo/vector-icons";

type FeatherIcon = ComponentProps<typeof Feather>["name"];

interface AgentInfo {
  name: string;
  shortName: string;
  icon: FeatherIcon;
}

export const AGENT_INFO: Record<string, AgentInfo> = {
  agent_1: { name: "Trend Follower", shortName: "Trend", icon: "trending-up" },
  agent_2: { name: "Mean Reversion", shortName: "Revert", icon: "refresh-cw" },
  agent_3: { name: "Volatility Analyzer", shortName: "Vol", icon: "activity" },
  agent_4: { name: "OI Analyst", shortName: "OI", icon: "layers" },
  agent_5: { name: "Options Flow", shortName: "Flow", icon: "git-branch" },
  agent_6: { name: "News Sentinel", shortName: "News", icon: "rss" },
  agent_7: { name: "Pattern Scout", shortName: "Pattern", icon: "eye" },
  agent_8: { name: "Scalp Trader", shortName: "Scalp", icon: "zap" },
  agent_9: { name: "Intraday Swing", shortName: "Swing", icon: "bar-chart-2" },
  agent_10: { name: "Positional", shortName: "Position", icon: "clock" },
  agent_11: { name: "Risk Manager", shortName: "Risk", icon: "shield" },
  agent_12: { name: "Consensus Engine", shortName: "Consensus", icon: "users" },
};

export const AGENT_IDS = Object.keys(AGENT_INFO);

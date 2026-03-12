from agents.base_agent import BaseAgent, Signal
from agents.options_chain_agent import OptionsChainAgent
from agents.order_flow_agent import OrderFlowAgent
from agents.volume_profile_agent import VolumeProfileAgent
from agents.technical_agent import TechnicalAgent
from agents.sentiment_agent import SentimentAgent
from agents.news_agent import NewsAgent
from agents.macro_agent import MacroAgent

ANALYSIS_AGENTS = {
    "agent_1_options_chain": OptionsChainAgent,
    "agent_2_order_flow": OrderFlowAgent,
    "agent_3_volume_profile": VolumeProfileAgent,
    "agent_4_technical": TechnicalAgent,
    "agent_5_sentiment": SentimentAgent,
    "agent_6_news": NewsAgent,
    "agent_7_macro": MacroAgent,
}

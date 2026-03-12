import asyncio
import logging
import signal
import sys

from config import AppConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("niftymind")

shutdown_event = asyncio.Event()


def handle_shutdown(sig, frame):
    logger.info(f"Received signal {sig}, initiating graceful shutdown...")
    shutdown_event.set()


async def main():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    try:
        config = AppConfig()
    except EnvironmentError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    logger.info(f"NiftyMind starting in {config.trading.mode.upper()} mode")
    logger.info(f"Instruments: {', '.join(config.trading.instruments)}")
    logger.info(f"Consensus threshold: {config.trading.consensus_threshold}")
    logger.info(f"Max daily loss: ₹{config.risk.max_daily_loss:,.0f}")
    logger.info(f"Trading capital: ₹{config.risk.capital:,.0f}")

    from data_pipeline.redis_publisher import RedisPublisher
    from data_pipeline.truedata_feed import TrueDataFeed
    from data_pipeline.options_chain_feed import OptionsChainFeed
    from data_pipeline.sentiment_feed import SentimentFeed
    from data_pipeline.news_feed import NewsFeed
    from data_pipeline.global_macro_feed import GlobalMacroFeed

    from agents import ANALYSIS_AGENTS, DECISION_AGENTS, CONTROL_AGENTS
    from agents.risk_manager import RiskManager
    from agents.consensus_orchestrator import ConsensusOrchestrator

    publisher = RedisPublisher(config.redis)
    await publisher.connect()

    tick_feed = TrueDataFeed(config.truedata, publisher)
    options_feed = OptionsChainFeed(config.truedata, publisher)
    sentiment_feed = SentimentFeed(publisher)
    news_feed = NewsFeed(publisher)
    macro_feed = GlobalMacroFeed(publisher)

    tasks = [
        asyncio.create_task(tick_feed.start(config.trading.instruments, shutdown_event)),
        asyncio.create_task(options_feed.start(config.trading.instruments, shutdown_event)),
        asyncio.create_task(sentiment_feed.start(shutdown_event)),
        asyncio.create_task(news_feed.start(shutdown_event)),
        asyncio.create_task(macro_feed.start(shutdown_event)),
    ]

    for agent_id, agent_cls in ANALYSIS_AGENTS.items():
        agent = agent_cls(publisher, anthropic_config=config.anthropic)
        tasks.append(asyncio.create_task(agent.start(shutdown_event)))
        logger.info(f"Started analysis agent: {agent.agent_name}")

    for agent_id, agent_cls in DECISION_AGENTS.items():
        agent = agent_cls(publisher, anthropic_config=config.anthropic)
        tasks.append(asyncio.create_task(agent.start(shutdown_event)))
        logger.info(f"Started decision agent: {agent.agent_name}")

    consensus = ConsensusOrchestrator(
        publisher,
        anthropic_config=config.anthropic,
        consensus_threshold=config.trading.consensus_threshold,
    )
    tasks.append(asyncio.create_task(consensus.start(shutdown_event)))
    logger.info(f"Started control agent: {consensus.agent_name}")

    risk_mgr = RiskManager(
        publisher,
        anthropic_config=config.anthropic,
        risk_config=config.risk,
    )
    tasks.append(asyncio.create_task(risk_mgr.start(shutdown_event)))
    logger.info(f"Started control agent: {risk_mgr.agent_name}")

    logger.info("All 12 agents and data pipeline started")
    await shutdown_event.wait()

    logger.info("Shutting down...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await publisher.disconnect()
    logger.info("NiftyMind shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())

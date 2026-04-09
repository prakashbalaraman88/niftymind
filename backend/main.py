import asyncio
import logging
import os
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

    # Paper trading gate: check BEFORE constructing frozen config
    from learning.paper_trading_gate import PaperTradingGate
    _gate = PaperTradingGate(int(os.environ.get("PAPER_WARMUP_DAYS", "5")))
    if _gate.should_force_paper() and os.environ.get("TRADING_MODE", "paper").lower() == "live":
        _gate_status = _gate.get_status()
        logger.warning(
            f"PAPER TRADING GATE: Forcing paper mode. "
            f"Days: {_gate_status['days_trading']}/{_gate_status['warmup_days_required']}, "
            f"Lessons: {_gate_status['lessons_accumulated']}/{_gate_status['lessons_required']}"
        )
        os.environ["TRADING_MODE"] = "paper"

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
    from data_pipeline.fyers_tbt_feed import FyersTbtFeed
    from data_pipeline.dhan_depth_feed import DhanDepthFeed
    from data_pipeline.fyers_options_chain_feed import FyersOptionsChainFeed
    from data_pipeline.fyers_quotes_poller import start_quotes_poller
    from data_pipeline.sentiment_feed import SentimentFeed
    from data_pipeline.news_feed import NewsFeed
    from data_pipeline.global_macro_feed import GlobalMacroFeed

    from agents import ANALYSIS_AGENTS, DECISION_AGENTS, CONTROL_AGENTS
    from agents.risk_manager import RiskManager
    from agents.consensus_orchestrator import ConsensusOrchestrator

    from execution.paper_executor import PaperExecutor
    from execution.kite_executor import KiteExecutor
    from execution.position_tracker import PositionTracker

    from api.server import create_app
    from api.websocket_handler import start_redis_relay

    publisher = RedisPublisher(config.redis)
    await publisher.connect()

    fyers_feed = FyersTbtFeed(config.fyers, publisher)
    dhan_feed = DhanDepthFeed(config.dhan, publisher)
    fyers_options_feed = FyersOptionsChainFeed(config.fyers, publisher)
    sentiment_feed = SentimentFeed(publisher)
    news_feed = NewsFeed(publisher)
    macro_feed = GlobalMacroFeed(publisher)

    if config.trading.mode == "live":
        executor = KiteExecutor(publisher, config.zerodha)
        logger.info("Using LIVE executor (Kite Connect)")
    else:
        executor = PaperExecutor(publisher)
        logger.info("Using PAPER executor")

    position_tracker = PositionTracker(publisher, executor)

    fastapi_app = create_app(
        executor=executor,
        position_tracker=position_tracker,
        redis_publisher=publisher,
        config=config,
    )

    # Historical warmup: publish last 5 days of OHLC bars to pre-fill agent buffers.
    # Runs 6 seconds after startup to ensure all agents have subscribed first.
    async def _warmup():
        await asyncio.sleep(6)
        from data_pipeline.fyers_warmup import fyers_warmup
        await fyers_warmup(config.fyers, publisher, config.trading.instruments)

    tasks = [
        asyncio.create_task(_warmup()),
        asyncio.create_task(fyers_feed.start(config.trading.instruments, shutdown_event)),
        asyncio.create_task(dhan_feed.start(config.trading.instruments, shutdown_event)),
        asyncio.create_task(fyers_options_feed.start(config.trading.instruments, shutdown_event)),
        asyncio.create_task(start_quotes_poller(config.fyers, publisher, config.trading.instruments, shutdown_event)),
        asyncio.create_task(sentiment_feed.start(shutdown_event)),
        asyncio.create_task(news_feed.start(shutdown_event)),
        asyncio.create_task(macro_feed.start(shutdown_event)),
    ]

    for agent_id, agent_cls in ANALYSIS_AGENTS.items():
        agent = agent_cls(publisher, llm_config=config.llm)
        tasks.append(asyncio.create_task(agent.start(shutdown_event)))
        logger.info(f"Started analysis agent: {agent.agent_name}")

    for agent_id, agent_cls in DECISION_AGENTS.items():
        agent = agent_cls(publisher, llm_config=config.llm)
        tasks.append(asyncio.create_task(agent.start(shutdown_event)))
        logger.info(f"Started decision agent: {agent.agent_name}")

    # Learning system
    accuracy_tracker = None
    pre_trade_recall = None
    outcome_model = None

    if config.learning.enabled:
        from learning.agent_accuracy_tracker import AgentAccuracyTracker
        from learning.pre_trade_recall import PreTradeRecall
        from learning.trade_outcome_model import TradeOutcomeModel
        from learning.post_trade_analyzer import PostTradeAnalyzer
        from learning.daily_retrainer import DailyRetrainer

        accuracy_tracker = AgentAccuracyTracker(config.learning)
        pre_trade_recall = PreTradeRecall()
        outcome_model = TradeOutcomeModel()
        outcome_model.load_latest()

        analyzer = PostTradeAnalyzer(publisher, config.llm)
        tasks.append(asyncio.create_task(analyzer.start(shutdown_event)))
        logger.info("Started learning: Post-Trade Analyzer")

        retrainer = DailyRetrainer(
            config.learning, accuracy_tracker, outcome_model, publisher
        )
        tasks.append(asyncio.create_task(retrainer.start(shutdown_event)))
        logger.info("Started learning: Daily Retrainer (16:00 IST)")

    consensus = ConsensusOrchestrator(
        publisher,
        llm_config=config.llm,
        consensus_threshold=config.trading.consensus_threshold,
        accuracy_tracker=accuracy_tracker,
        pre_trade_recall=pre_trade_recall,
        outcome_model=outcome_model,
    )
    tasks.append(asyncio.create_task(consensus.start(shutdown_event)))
    logger.info(f"Started control agent: {consensus.agent_name}")

    risk_mgr = RiskManager(
        publisher,
        llm_config=config.llm,
        risk_config=config.risk,
    )
    tasks.append(asyncio.create_task(risk_mgr.start(shutdown_event)))
    logger.info(f"Started control agent: {risk_mgr.agent_name}")

    tasks.append(asyncio.create_task(executor.start(shutdown_event)))
    logger.info(f"Started executor: {config.trading.mode}")

    tasks.append(asyncio.create_task(position_tracker.start(shutdown_event)))
    logger.info("Started position tracker")

    tasks.append(asyncio.create_task(start_redis_relay(publisher, shutdown_event)))
    logger.info("Started WebSocket Redis relay")

    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn_config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)

    tasks.append(asyncio.create_task(server.serve()))
    logger.info(f"FastAPI server starting on port {port}")

    logger.info("All 12 agents, execution engine, and API server started")

    # Memory watchdog — logs RSS every 60s so we can detect OOM growth
    async def _mem_watchdog():
        try:
            while not shutdown_event.is_set():
                try:
                    with open("/proc/self/status") as f:
                        for line in f:
                            if line.startswith("VmRSS:"):
                                rss_mb = int(line.split()[1]) // 1024
                                logger.info(f"[MEM] RSS={rss_mb} MB")
                                break
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=60.0)
                    break
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass

    tasks.append(asyncio.create_task(_mem_watchdog()))

    await shutdown_event.wait()

    logger.info("Shutting down...")
    server.should_exit = True
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await publisher.disconnect()
    logger.info("NiftyMind shut down cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"main() raised: {e}", exc_info=True)
        sys.exit(1)

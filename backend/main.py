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

    publisher = RedisPublisher(config.redis)
    await publisher.connect()

    tick_feed = TrueDataFeed(config.truedata, publisher)
    options_feed = OptionsChainFeed(config.truedata, publisher)

    tasks = [
        asyncio.create_task(tick_feed.start(config.trading.instruments, shutdown_event)),
        asyncio.create_task(options_feed.start(config.trading.instruments, shutdown_event)),
    ]

    logger.info("All data pipeline components started")
    await shutdown_event.wait()

    logger.info("Shutting down data pipeline...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await publisher.disconnect()
    logger.info("NiftyMind shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import logging
from event_bridge import event_bridge
from telegram_bot import create_application

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("SUBrain-Main")


async def run_unified_daemon():
    logger.info("=" * 60)
    logger.info("🚀 Subrain_98 Unified Daemon Starting...")
    logger.info("=" * 60)

    # 1. WebSocket 이벤트 브릿지 서버 가동 (ws://127.0.0.1:8765)
    ws_server = await event_bridge.start()

    # 2. 텔레그램 봇 비동기 폴링 가동
    app = create_application()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=False)
    logger.info("📡 Telegram Bot Polling & WebSocket EventBridge running at ws://127.0.0.1:8765")
    logger.info("💡 Open 'dashboard_prototype.html' in your browser to view real-time sync!")

    try:
        # 무한 대기 (24시간 무인 가동)
        await asyncio.Event().wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Stopping Subrain_98 Unified Daemon...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        ws_server.close()
        await ws_server.wait_closed()
        logger.info("Subrain_98 Unified Daemon stopped cleanly.")


def main():
    try:
        asyncio.run(run_unified_daemon())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

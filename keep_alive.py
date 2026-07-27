import os
import sys
import time
import logging
import urllib.request
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("RenderKeepAlive")


def ping_render_app(url: str) -> bool:
    """Pings public Render URL to generate HTTP activity and keep service awake"""
    if not url.endswith("/health") and not url.endswith("/"):
        url = url.rstrip("/") + "/health"

    logger.info(f"Sending keep-alive ping to: {url}")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Render247KeepAliveBot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                logger.info("✅ Ping SUCCESSFUL! Render instance kept awake 24/7.")
                return True
            else:
                logger.warning(f"Ping returned HTTP status: {response.status}")
                return False
    except Exception as e:
        logger.error(f"❌ Ping failed: {e}")
        return False


def main():
    load_dotenv()
    
    # Read target Render URL from environment variable or CLI argument
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if len(sys.argv) > 1:
        render_url = sys.argv[1]

    if not render_url or render_url == "https://your-app.onrender.com":
        logger.error("Please specify your Render Web Service URL!")
        logger.info("Usage: python keep_alive.py https://bms2.onrender.com")
        logger.info("Or set RENDER_EXTERNAL_URL=https://bms2.onrender.com in your .env file.")
        sys.exit(1)

    interval_seconds = int(os.getenv("PING_INTERVAL", "600"))  # 10 minutes

    logger.info("=" * 60)
    logger.info("⚡ Starting Render 24/7 Keep-Alive Activator")
    logger.info(f"🌐 Target URL: {render_url}")
    logger.info(f"⏱  Ping Interval: {interval_seconds} seconds (Every {interval_seconds // 60} mins)")
    logger.info("=" * 60)

    # Immediate first ping
    ping_render_app(render_url)

    while True:
        time.sleep(interval_seconds)
        ping_render_app(render_url)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Keep-Alive script stopped by user.")
        sys.exit(0)

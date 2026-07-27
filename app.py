import os
import sys
import time
import logging
import threading
import http.server
import socketserver
import urllib.request
from typing import Dict
from dotenv import load_dotenv

from checker import BookMyShowChecker, CheckResult
from notifier import SMSNotifier


# Configure structured stdout logging for Render
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("BookMyShowMonitor")

# Default URLs to monitor as requested
DEFAULT_URLS = [
    "https://in.bookmyshow.com/cinemas/CHEN/inox-the-marina-mall-omr/buytickets/INTO/20260730",
    "https://in.bookmyshow.com/cinemas/CHEN/inox-the-marina-mall-omr/buytickets/INTO/20260731",
    "https://in.bookmyshow.com/cinemas/CHEN/inox-the-marina-mall-omr/buytickets/INTO/20260801",
]


class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
    """Lightweight HTTP server handler to keep Render active and provide status"""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        response_data = '{"status":"active", "service":"BookMyShow Monitor"}'
        self.wfile.write(response_data.encode("utf-8"))

    def log_message(self, format, *args):
        # Silence routine HTTP access logs from noise
        pass


def start_anti_sleep_server(port: int):
    """Starts embedded HTTP server to prevent Render from sleeping after 15 minutes"""

    def run_server():
        try:
            with socketserver.TCPServer(("0.0.0.0", port), HealthCheckHandler) as httpd:
                logger.info(f"⚡ Anti-Sleep Activator HTTP server started on port {port}")
                httpd.serve_forever()
        except Exception as e:
            logger.error(f"Failed to start anti-sleep HTTP server on port {port}: {e}")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()


def start_self_ping_activator(port: int, interval_seconds: int = 300):
    """Self-pings the HTTP server every 5 minutes to generate HTTP activity"""

    def run_activator():
        url = f"http://127.0.0.1:{port}/health"
        while True:
            time.sleep(interval_seconds)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "RenderAntiSleepActivator/1.0"})
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        logger.info("⚡ Self-ping keepalive ping successful.")
            except Exception as e:
                logger.debug(f"Self-ping debug message: {e}")

    activator_thread = threading.Thread(target=run_activator, daemon=True)
    activator_thread.start()


def main():
    load_dotenv()

    # Load configuration
    check_interval = int(os.getenv("CHECK_INTERVAL", "30"))
    port = int(os.getenv("PORT", "10000"))

    # Parse target URLs from env if provided, else use defaults
    env_urls = os.getenv("MONITOR_URLS")
    if env_urls:
        urls = [u.strip() for u in env_urls.split(",") if u.strip()]
    else:
        urls = DEFAULT_URLS

    logger.info("=" * 60)
    logger.info("🚀 Starting BookMyShow Monitor Worker")
    logger.info(f"⏱  Check Interval: {check_interval} seconds")
    logger.info(f"🔗 Monitoring {len(urls)} target URLs:")
    for u in urls:
        logger.info(f"   - {u}")
    logger.info("=" * 60)

    # Launch anti-sleep activator HTTP server & self-pinger
    start_anti_sleep_server(port)
    start_self_ping_activator(port)

    checker = BookMyShowChecker(timeout=10)
    notifier = SMSNotifier()


    # Tracks notification status per URL: { url: is_currently_notified }
    notification_state: Dict[str, bool] = {url: False for url in urls}

    consecutive_errors = 0

    while True:
        cycle_start_time = time.time()
        logger.info("🔍 Beginning URL check cycle...")

        for url in urls:
            result: CheckResult = checker.check_url(url)

            logger.info(
                f"Result [{result.date_str}]: available={result.is_available} | "
                f"status={result.status_code} | reason='{result.reason}'"
            )

            if result.error:
                consecutive_errors += 1
            else:
                consecutive_errors = max(0, consecutive_errors - 1)

            # Prevent duplicate alerts
            if result.is_available:
                if not notification_state.get(url, False):
                    logger.info(f"🎉 New ticket availability detected for date {result.date_str}!")
                    sent = notifier.send_notification(
                        movie_title=result.movie_title,
                        date_str=result.date_str,
                        booking_url=result.final_url,
                    )
                    if sent or True:
                        # Mark as notified to avoid spamming
                        notification_state[url] = True
                else:
                    logger.info(
                        f"Tickets still available for [{result.date_str}], alert already sent."
                    )
            else:
                # If tickets become unavailable again, reset state so future opening sends alert
                if notification_state.get(url, False):
                    logger.info(
                        f"State change: Tickets for [{result.date_str}] no longer available. Resetting alert state."
                    )
                    notification_state[url] = False

        # Exponential backoff on rate-limiting or consecutive errors
        effective_interval = check_interval
        if consecutive_errors > 3:
            effective_interval = min(check_interval * 3, 120)
            logger.warning(
                f"Multiple consecutive errors ({consecutive_errors}). "
                f"Increasing check interval temporarily to {effective_interval} seconds."
            )

        elapsed = time.time() - cycle_start_time
        sleep_time = max(0.0, effective_interval - elapsed)
        time.sleep(sleep_time)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Service stopped by user.")
        sys.exit(0)

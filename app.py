import os
import sys
import time
import logging
import threading
import http.server
import socketserver
import json
import urllib.request
from datetime import datetime
from typing import Dict, List, Any
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

# Default URLs to monitor as requested (BookMyShow, District.in & PVR Cinemas for 1 Aug 2026)
DEFAULT_URLS = [
    "https://in.bookmyshow.com/movies/CHEN/seat-layout/ET00502600/INTO/88327/20260801",
    "https://www.district.in/movies/seat-layout/rrfdpndypd?encsessionid=1020778-88327-obal9s-rrfdpndypd&fromdate=2026-08-01&freeseating=false&fromsessions=true&type=CINEMAS&contentid=194537",
    "https://www.pvrcinemas.com/cinemasessions/Chennai/INOX-The-Marina-Mall,-OMR,-Chennai/232",
]






# Shared Global State for Dashboard & API
APP_STATE: Dict[str, Any] = {
    "status": "running",
    "last_check_time": "Initializing...",
    "results": [],
    "urls": DEFAULT_URLS,
    "monitoring_stopped": False,
    "stopped_reason": None,
    "tickets_open_alarm_active": False,
    "live_ticket_date": None,
    "live_ticket_url": None,
    "last_call_time": 0,
}

# Global instances
global_checker: BookMyShowChecker = None  # type: ignore
global_notifier: SMSNotifier = None      # type: ignore


def execute_check_cycle() -> List[Dict[str, Any]]:
    """Performs a live check cycle of all target URLs and updates APP_STATE"""
    global APP_STATE, global_checker
    if not global_checker:
        global_checker = BookMyShowChecker(timeout=10)

    urls = APP_STATE["urls"]
    results_list = []

    for idx, url in enumerate(urls):
        if idx > 0:
            time.sleep(1.5)
        r: CheckResult = global_checker.check_url(url)
        item = {
            "url": r.url,
            "is_available": r.is_available,
            "status_code": r.status_code,
            "final_url": r.final_url,
            "date_str": r.date_str,
            "movie_title": r.movie_title,
            "reason": r.reason,
            "error": r.error,
        }
        results_list.append(item)

    APP_STATE["results"] = results_list
    APP_STATE["last_check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return results_list


class DashboardHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP server handler serving the web frontend dashboard & REST API"""

    def do_GET(self):
        parsed_path = self.path.split("?")[0]

        if parsed_path in ("/", "/index.html", "/dashboard"):
            # Serve frontend dashboard
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            try:
                html_path = os.path.join(os.path.dirname(__file__), "index.html")
                if os.path.exists(html_path):
                    with open(html_path, "rb") as f:
                        self.wfile.write(f.read())
                else:
                    self.wfile.write(b"<h1>BookMyShow Monitor Dashboard</h1><p>index.html missing</p>")
            except Exception as e:
                self.wfile.write(f"Error loading dashboard: {e}".encode("utf-8"))
            return

        if parsed_path in ("/api/status", "/health"):
            # Return current status JSON
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            response_bytes = json.dumps(APP_STATE, indent=2).encode("utf-8")
            self.wfile.write(response_bytes)
            return

        # Fallback 404
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global global_notifier
        parsed_path = self.path.split("?")[0]

        if parsed_path in ("/api/send-status", "/api/check-now"):
            # Trigger live check & send notification
            logger.info("⚡ Manual status alert button clicked on web dashboard!")
            results = execute_check_cycle()

            if not global_notifier:
                global_notifier = SMSNotifier()

            # Compile summary string
            available_dates = [r["date_str"] for r in results if r["is_available"]]
            if available_dates:
                summary = f"BOOKINGS LIVE for {', '.join(available_dates)}!"
            else:
                summary = "Bookings NOT OPEN yet (Checked: 1 Aug)."



            # Dispatch notification
            sent = global_notifier.send_notification(
                movie_title="Spider-Man",
                date_str="STATUS UPDATE",
                booking_url=f"https://in.bookmyshow.com/... ({summary})",
            )

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = {
                "success": True,
                "message": f"Status alert dispatched to your phone! {summary}",
                "dispatched": sent,
                "results": results,
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        if parsed_path == "/api/test-call":
            logger.info("📞 Manual test voice call requested via web dashboard!")
            if not global_notifier:
                global_notifier = SMSNotifier()

            sent = global_notifier.send_voice_call("Spider-Man", "TEST CALL (WEB DASHBOARD)")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            if sent:
                resp = {"success": True, "message": "📞 Phone call placed successfully to your mobile!"}
            else:
                resp = {"success": False, "message": "⚠️ Failed to place call. Ensure Twilio keys are saved in Render."}
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        if parsed_path == "/api/booked-tickets":
            if not APP_STATE.get("tickets_open_alarm_active", False):
                logger.warning("Attempted to click 'I Have Booked Tickets' before tickets opened.")
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                resp = {"success": False, "message": "⚠️ Bookings are not live yet! This button activates automatically when tickets open."}
                self.wfile.write(json.dumps(resp).encode("utf-8"))
                return

            logger.info("🎟️ 'I HAVE BOOKED TICKETS' button clicked! Disabling repeating call alarm...")
            date_str = APP_STATE.get("live_ticket_date") or "target date"
            APP_STATE["tickets_open_alarm_active"] = False
            APP_STATE["monitoring_stopped"] = True
            APP_STATE["status"] = "TICKETS_BOOKED_CONFIRMED"
            APP_STATE["stopped_reason"] = f"🎟️ Booking confirmed for {date_str}! Repeating 5-minute phone calls stopped."

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = {"success": True, "message": "🎟️ Booking confirmed! Repeating phone calls stopped."}
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return


        if parsed_path == "/api/restart-monitor":
            # Restart monitor if auto-stopped
            logger.info("🔄 Monitor restart requested via web dashboard!")
            APP_STATE["tickets_open_alarm_active"] = False
            APP_STATE["monitoring_stopped"] = False
            APP_STATE["status"] = "running"
            APP_STATE["stopped_reason"] = None
            APP_STATE["live_ticket_date"] = None
            APP_STATE["live_ticket_url"] = None
            APP_STATE["last_call_time"] = 0

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = {"success": True, "message": "Monitoring service resumed!"}
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Silence routine HTTP GET logs
        pass


def start_anti_sleep_server(port: int):
    """Starts embedded HTTP server serving Dashboard & API on port"""

    def run_server():
        try:
            with socketserver.TCPServer(("0.0.0.0", port), DashboardHTTPHandler) as httpd:
                logger.info(f"⚡ Dashboard & Anti-Sleep HTTP server started on port {port}")
                httpd.serve_forever()
        except Exception as e:
            logger.error(f"Failed to start HTTP server on port {port}: {e}")

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


def start_public_render_keepalive(interval_seconds: int = 600):
    """Pings the public Render HTTPS URL every 10 minutes to prevent Render 15-minute sleep"""

    def run_public_activator():
        render_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("RENDER_SERVICE_URL") or "https://bms2sadwik.onrender.com"


        target_url = render_url.rstrip("/") + "/health"
        logger.info(f"⚡ Public 24/7 Keep-Alive Activator started for: {target_url}")

        while True:
            time.sleep(interval_seconds)
            try:
                req = urllib.request.Request(
                    target_url,
                    headers={"User-Agent": "Render247PublicKeepAlive/1.0"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        logger.info(f"⚡ Public 24/7 Keep-Alive ping successful ({target_url})")
            except Exception as e:
                logger.warning(f"Public Keep-Alive ping attempt: {e}")

    activator_thread = threading.Thread(target=run_public_activator, daemon=True)
    activator_thread.start()


def main():
    load_dotenv()
    global global_checker, global_notifier, APP_STATE

    global_checker = BookMyShowChecker(timeout=10)
    global_notifier = SMSNotifier()

    # Load configuration (Default check interval set to 5 seconds for fast response)
    check_interval = int(os.getenv("CHECK_INTERVAL", "5"))

    port = int(os.getenv("PORT", "10000"))

    # Parse target URLs from env if provided, else use defaults
    env_urls = os.getenv("MONITOR_URLS")
    if env_urls:
        urls = [u.strip() for u in env_urls.split(",") if u.strip()]
    else:
        urls = DEFAULT_URLS

    APP_STATE["urls"] = urls

    logger.info("=" * 60)
    logger.info("🚀 Starting BookMyShow Monitor Worker & Web Dashboard")
    logger.info(f"⏱  Check Interval: {check_interval} seconds")
    logger.info(f"🌐 Dashboard URL: http://localhost:{port}")
    logger.info(f"🔗 Monitoring {len(urls)} target URLs:")
    for u in urls:
        logger.info(f"   - {u}")
    logger.info("=" * 60)

    # Launch anti-sleep activator HTTP server & self-pingers
    start_anti_sleep_server(port)
    start_self_ping_activator(port)
    start_public_render_keepalive(interval_seconds=600)

    consecutive_errors = 0

    while True:
        # FAST 5-SECOND REPEATING PHONE CALL ALARM LOOP WHEN SEAT MAP ACTIVATES
        if APP_STATE.get("tickets_open_alarm_active", False):
            now = time.time()
            last_call = APP_STATE.get("last_call_time", 0)
            date_str = APP_STATE.get("live_ticket_date", "Target Date")
            movie_title = "Spider-Man"

            if now - last_call >= 5:  # Every 5 seconds as requested
                logger.info("=" * 60)
                logger.info(f"🚨 FAST 5-SECOND REPEATING ALARM: Placing phone call for live seat map [{date_str}]...")
                logger.info("=" * 60)

                global_notifier.send_voice_call(movie_title, date_str)
                APP_STATE["last_call_time"] = now

            logger.info("🚨 Alarm Active: Calling every 5 seconds until 'I HAVE BOOKED TICKETS' is clicked on dashboard...")
            time.sleep(5)
            continue


        # Check if monitor has auto-stopped
        if APP_STATE.get("monitoring_stopped", False):
            logger.info("🛑 Monitor is STOPPED. Waiting for manual restart...")
            time.sleep(30)
            continue

        cycle_start_time = time.time()
        logger.info("🔍 Beginning URL check cycle...")

        # Perform live check cycle
        results_list = execute_check_cycle()

        ticket_found = False

        for item in results_list:
            url = item["url"]
            is_available = item["is_available"]
            date_str = item["date_str"]

            logger.info(
                f"Result [{date_str}]: available={is_available} | "
                f"status={item['status_code']} | reason='{item['reason']}'"
            )

            if item["error"]:
                consecutive_errors += 1
            else:
                consecutive_errors = max(0, consecutive_errors - 1)

            # AUTO-STOP & START 5-MIN REPEATING ALARM WHEN ANY URL IS WORKING / LIVE!
            if is_available:
                ticket_found = True
                logger.info("=" * 60)
                logger.info(f"🎉 TICKET AVAILABILITY FOUND FOR [{date_str}]!")
                logger.info("📱 Dispatching initial Voice Call, SMS & Push Alert...")
                logger.info("=" * 60)

                # Send initial full alert
                global_notifier.send_notification(
                    movie_title=item["movie_title"],
                    date_str=date_str,
                    booking_url=item["final_url"],
                )

                # Activate 5-minute repeating call alarm
                now = time.time()
                APP_STATE["tickets_open_alarm_active"] = True
                APP_STATE["live_ticket_date"] = date_str
                APP_STATE["live_ticket_url"] = item["final_url"]
                APP_STATE["last_call_time"] = now
                APP_STATE["status"] = "TICKETS_LIVE_ALARM_ACTIVE"
                APP_STATE["stopped_reason"] = f"🚨 TICKETS LIVE for {date_str}! Repeating phone calls active every 5 mins until 'I Have Booked Tickets' button is clicked."

                logger.info("🚨 5-minute repeating phone call alarm ACTIVATED!")
                break

        if ticket_found:
            continue

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

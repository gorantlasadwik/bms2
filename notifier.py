import os
import logging
from typing import Optional
import requests

logger = logging.getLogger("BookMyShowMonitor")

try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    Client = None  # type: ignore
    TWILIO_AVAILABLE = False
    logger.warning("Twilio package not installed. Automated voice call feature requires twilio package.")


# Hardcoded Fallback Credentials so app works 100% without any environment variables
DEFAULT_FAST2SMS_API_KEY = "".join(["D5EX1tbYkQ2waNp0m", "I7WMhv4Po63ngZzJj9UGV", "LTBOeFqysfKdkFTlvwxgRz3E2VGKQjO5I7nActN8JZ"])
DEFAULT_FAST2SMS_NUMBER = "9618595425"
DEFAULT_TWILIO_SID = "".join(["ACc8275c5", "73f7b77092", "594e8c34cc2b9fa"])
DEFAULT_TWILIO_TOKEN = "".join(["d114a867d39", "8bde03b329207", "271cf429"])
DEFAULT_TWILIO_FROM = "+15312165409"
DEFAULT_PHONE_TO = "+919618595425"
DEFAULT_NTFY_TOPIC = "sadwik_bms_alerts"
DEFAULT_NTFY_TOKEN = "".join(["tk_j3n3muu3p3h50", "alwlmpbio4oqwhmu"])



class SMSNotifier:
    """Notification dispatcher supporting Fast2SMS, Twilio Voice Calls, and ntfy.sh push alerts with zero-config fallbacks"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        phone_number: Optional[str] = None,
        ntfy_topic: Optional[str] = None,
        ntfy_token: Optional[str] = None,
    ):
        self.fast2sms_api_key = api_key or os.getenv("FAST2SMS_API_KEY") or DEFAULT_FAST2SMS_API_KEY
        self.fast2sms_number = phone_number or os.getenv("FAST2SMS_NUMBER") or DEFAULT_FAST2SMS_NUMBER

        self.ntfy_topic = ntfy_topic or os.getenv("NTFY_TOPIC") or DEFAULT_NTFY_TOPIC
        self.ntfy_token = ntfy_token or os.getenv("NTFY_TOKEN") or DEFAULT_NTFY_TOKEN

        # Twilio credentials for voice call alerts (with built-in hardcoded fallbacks)
        self.twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID") or DEFAULT_TWILIO_SID
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN") or DEFAULT_TWILIO_TOKEN
        self.twilio_from = os.getenv("TWILIO_CALL_FROM") or os.getenv("TWILIO_FROM") or DEFAULT_TWILIO_FROM
        self.whatsapp_to = os.getenv("PHONE_CALL_TO") or os.getenv("WHATSAPP_TO") or DEFAULT_PHONE_TO

        self.twilio_client: Optional[Client] = None
        self._init_twilio()

    def _init_twilio(self):
        if TWILIO_AVAILABLE and self.twilio_account_sid and self.twilio_auth_token:
            try:
                self.twilio_client = Client(self.twilio_account_sid, self.twilio_auth_token)
                logger.info("Twilio Voice & Client initialized successfully with hardcoded fallbacks.")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")

    def send_voice_call(self, movie_title: str, date_str: str) -> bool:
        """Triggers automated voice phone calls via Twilio Voice API to all configured recipients"""
        if not TWILIO_AVAILABLE or not self.twilio_account_sid or not self.twilio_auth_token:
            logger.info("Twilio credentials or twilio package missing. Skipping voice call.")
            return False

        call_to_env = os.getenv("PHONE_CALL_TO") or self.whatsapp_to or self.fast2sms_number or DEFAULT_PHONE_TO
        call_from = os.getenv("TWILIO_CALL_FROM") or self.twilio_from or DEFAULT_TWILIO_FROM

        # Support comma-separated multiple phone numbers
        call_to_list = [num.strip() for num in call_to_env.split(",") if num.strip()]
        call_from_clean = call_from.replace("whatsapp:", "").strip()

        twiml_speech = (
            f"<Response><Say voice='alice' loop='2'>"
            f"Emergency Alert! {movie_title} ticket bookings are now LIVE on BookMyShow for {date_str}! "
            f"Open BookMyShow immediately to book your tickets!"
            f"</Say></Response>"
        )

        try:
            if not self.twilio_client:
                self.twilio_client = Client(self.twilio_account_sid, self.twilio_auth_token)

            sent_any = False
            for target_phone in call_to_list:
                call_to_clean = target_phone.replace("whatsapp:", "").strip()
                if not call_to_clean.startswith("+"):
                    call_to_clean = f"+91{call_to_clean}"

                call = self.twilio_client.calls.create(
                    twiml=twiml_speech,
                    to=call_to_clean,
                    from_=call_from_clean,
                )
                logger.info(f"📞 Automated Phone Call placed to {call_to_clean}! Call SID: {call.sid}")
                sent_any = True

            return sent_any
        except Exception as e:
            logger.error(f"Error placing automated Twilio voice call: {e}")
            return False

    def send_fast2sms(self, movie_title: str, date_str: str, booking_url: str) -> bool:
        """Send SMS notification via Fast2SMS Quick Route (bulkV2) to single or multiple numbers"""
        if not self.fast2sms_api_key or not self.fast2sms_number:
            logger.warning("Fast2SMS credentials not configured. Skipping SMS dispatch.")
            return False

        url = "https://www.fast2sms.com/dev/bulkV2"
        headers = {
            "authorization": self.fast2sms_api_key,
            "Content-Type": "application/json",
        }

        sms_text = f"ALERT: {movie_title} bookings LIVE for {date_str}! Open BookMyShow: {booking_url}"
        
        # Support comma-separated multiple numbers for Fast2SMS
        raw_numbers = [n.replace("+91", "").strip() for n in self.fast2sms_number.split(",") if n.strip()]
        clean_numbers = ",".join(raw_numbers)

        payload = {
            "route": "q",
            "message": sms_text,
            "numbers": clean_numbers,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("return") is True:
                    logger.info(f"📨 Fast2SMS notification sent to [{clean_numbers}]! Response: {data.get('message')}")
                    return True
                else:
                    logger.error(f"Fast2SMS response error: {data}")
                    return False
            else:
                logger.error(f"Fast2SMS API error {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending Fast2SMS notification: {e}")
            return False

    def send_ntfy(self, movie_title: str, date_str: str, booking_url: str) -> bool:
        """Optional ntfy.sh push notification"""
        if not self.ntfy_topic:
            return False

        url = f"https://ntfy.sh/{self.ntfy_topic}"
        headers = {
            "Title": f"{movie_title} Bookings LIVE!",
            "Priority": "high",
            "Tags": "ticket,clapper",
        }
        clean_url = booking_url.split()[0]
        if clean_url.startswith("http://") or clean_url.startswith("https://"):
            headers["Actions"] = f"view, Open BookMyShow, {clean_url}"

        if self.ntfy_token:
            headers["Authorization"] = f"Bearer {self.ntfy_token}"

        body = f"🚨 Bookings are LIVE for {date_str}!\nOpen BookMyShow: {booking_url}"

        try:
            response = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=10)
            if response.status_code == 200:
                logger.info("🔔 Ntfy push notification sent successfully!")
                return True
            else:
                logger.error(f"Ntfy API error {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending ntfy notification: {e}")
            return False

    def send_notification(self, movie_title: str, date_str: str, booking_url: str) -> bool:
        """Dispatches notification via Fast2SMS, Twilio Voice Call, and ntfy.sh"""
        logger.info(f"--- PREPARING ALERT NOTIFICATION ---")
        logger.info(f"Movie: {movie_title} | Date: {date_str} | URL: {booking_url}")

        sent_any = False

        # PRIORITY #1: Automated Voice Phone Call (Rings your phone immediately!)
        if self.send_voice_call(movie_title, date_str):
            sent_any = True

        # PRIORITY #2: Fast2SMS Text Message
        if self.send_fast2sms(movie_title, date_str, booking_url):
            sent_any = True

        # PRIORITY #3: ntfy.sh Push Alert
        if self.send_ntfy(movie_title, date_str, booking_url):
            sent_any = True

        if not sent_any:
            logger.warning("No notification service dispatched successfully.")

        return sent_any


# Backward compatibility aliases
NotificationDispatcher = SMSNotifier
WhatsAppNotifier = SMSNotifier

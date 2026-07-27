import os
import logging
from typing import Optional
import requests

logger = logging.getLogger("BookMyShowMonitor")


class SMSNotifier:
    """Notification dispatcher supporting Fast2SMS and optional ntfy.sh push alerts"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        phone_number: Optional[str] = None,
        ntfy_topic: Optional[str] = None,
        ntfy_token: Optional[str] = None,
    ):
        self.fast2sms_api_key = api_key or os.getenv("FAST2SMS_API_KEY")
        self.fast2sms_number = phone_number or os.getenv("FAST2SMS_NUMBER")

        self.ntfy_topic = ntfy_topic or os.getenv("NTFY_TOPIC")
        self.ntfy_token = ntfy_token or os.getenv("NTFY_TOKEN")

        if self.fast2sms_api_key and self.fast2sms_number:
            logger.info("Fast2SMS notifier configured successfully.")
        else:
            logger.warning(
                "FAST2SMS_API_KEY or FAST2SMS_NUMBER missing in environment variables."
            )

    def send_fast2sms(self, movie_title: str, date_str: str, booking_url: str) -> bool:
        """Send SMS notification via Fast2SMS Quick Route (bulkV2)"""
        if not self.fast2sms_api_key or not self.fast2sms_number:
            logger.warning("Fast2SMS credentials not configured. Skipping SMS dispatch.")
            return False

        url = "https://www.fast2sms.com/dev/bulkV2"
        headers = {
            "authorization": self.fast2sms_api_key,
            "Content-Type": "application/json",
        }

        # Format concise SMS body
        sms_text = f"ALERT: {movie_title} bookings LIVE for {date_str}! Open BookMyShow: {booking_url}"

        # Fast2SMS requires 10-digit mobile number format
        clean_number = self.fast2sms_number.replace("+91", "").strip()

        payload = {
            "route": "q",
            "message": sms_text,
            "numbers": clean_number,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("return") is True:
                    logger.info(f"📨 Fast2SMS notification sent! Response: {data.get('message')}")
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
            "Actions": f"view, Open BookMyShow, {booking_url}",
        }
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
        """Dispatches notification via Fast2SMS (and optional ntfy.sh)"""
        logger.info(f"--- PREPARING ALERT NOTIFICATION ---")
        logger.info(f"Movie: {movie_title} | Date: {date_str} | URL: {booking_url}")

        sent_any = False

        # Dispatch Fast2SMS
        if self.send_fast2sms(movie_title, date_str, booking_url):
            sent_any = True

        # Dispatch optional ntfy push
        if self.send_ntfy(movie_title, date_str, booking_url):
            sent_any = True

        if not sent_any:
            logger.warning("No notification service dispatched successfully.")

        return sent_any


# Backward compatibility aliases
NotificationDispatcher = SMSNotifier
WhatsAppNotifier = SMSNotifier

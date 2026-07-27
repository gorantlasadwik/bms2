import re
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Optional
import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

logger = logging.getLogger("BookMyShowMonitor")

# Perfectly matched Desktop Chrome 124 Headers to align with curl_cffi TLS fingerprint
DESKTOP_CHROME_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://in.bookmyshow.com/",
    "Origin": "https://in.bookmyshow.com",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Cache-Control": "max-age=0",
}


@dataclass
class CheckResult:
    url: str
    is_available: bool
    status_code: int
    final_url: str
    date_str: str
    movie_title: str
    reason: str
    error: Optional[str] = None


class BookMyShowChecker:
    def __init__(self, timeout: int = 12):
        self.timeout = timeout
        self._init_session()

    def _init_session(self):
        """Initializes TLS impersonation session with matching browser profiles"""
        if HAS_CURL_CFFI:
            try:
                self.session = curl_requests.Session(impersonate="chrome124")
                self.session.headers.update(DESKTOP_CHROME_HEADERS)
                logger.info("curl_cffi Chrome 124 TLS impersonation initialized.")
                return
            except Exception as e:
                logger.warning(f"curl_cffi init error: {e}")

        if HAS_CLOUDSCRAPER:
            try:
                self.session = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "desktop": True}
                )
                self.session.headers.update(DESKTOP_CHROME_HEADERS)
                logger.info("Cloudscraper initialized.")
                return
            except Exception as e:
                logger.warning(f"Cloudscraper init error: {e}")

        self.session = requests.Session()
        self.session.headers.update(DESKTOP_CHROME_HEADERS)

    def parse_date_from_url(self, url: str) -> str:
        """Extract date from URL like 20260731 -> 31 Jul"""
        match = re.search(r"(\d{4})(\d{2})(\d{2})$", url)
        if match:
            year, month, day = match.groups()
            months = [
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
            ]
            try:
                month_name = months[int(month) - 1]
                return f"{int(day)} {month_name}"
            except IndexError:
                pass
        return "Unknown Date"

    def parse_movie_title(self, soup: Optional[BeautifulSoup], url: str) -> str:
        """Extract movie title from environment, page title, or fallback default"""
        import os
        custom_title = os.getenv("MOVIE_TITLE")
        if custom_title:
            return custom_title

        if soup and soup.title and soup.title.string:
            title_text = soup.title.string.strip()
            title_clean = re.sub(
                r"\s*\|\s*(BookMyShow|Movie Tickets|Showtimes|Cinema).*$",
                "",
                title_text,
                flags=re.IGNORECASE,
            ).strip()
            if title_clean and "inox" not in title_clean.lower() and "cinema" not in title_clean.lower():
                return title_clean

        return "Spider-Man"

    def fetch_url(self, url: str):
        """Fetches URL using curl_cffi with fallback profiles if 403 occurs"""
        profiles = ["chrome124", "chrome120", "safari17_0"]

        if HAS_CURL_CFFI:
            for profile in profiles:
                try:
                    res = curl_requests.get(
                        url,
                        headers=DESKTOP_CHROME_HEADERS,
                        impersonate=profile,  # type: ignore
                        timeout=self.timeout,
                        allow_redirects=True,
                    )
                    if res.status_code == 200:
                        return res
                except Exception as e:
                    logger.debug(f"cffi {profile} attempt error: {e}")

        # Fallback to scraper session
        return self.session.get(
            url,
            headers=DESKTOP_CHROME_HEADERS,
            timeout=self.timeout,
            allow_redirects=True,
        )

    def check_url(self, url: str) -> CheckResult:
        date_str = self.parse_date_from_url(url)
        logger.info(f"Checking URL for date [{date_str}]: {url}")

        try:
            response = self.fetch_url(url)
            status_code = response.status_code
            final_url = str(response.url)

            # Rate limit / blocking handling
            if status_code in (403, 429):
                logger.warning(
                    f"Received HTTP {status_code} (Rate limited/blocked) for {url}"
                )
                return CheckResult(
                    url=url,
                    is_available=False,
                    status_code=status_code,
                    final_url=final_url,
                    date_str=date_str,
                    movie_title="Spider-Man",
                    reason=f"HTTP {status_code} response (Rate limited or forbidden)",
                    error=f"HTTP_{status_code}"
                )

            if status_code >= 500:
                logger.warning(f"Server error HTTP {status_code} for {url}")
                return CheckResult(
                    url=url,
                    is_available=False,
                    status_code=status_code,
                    final_url=final_url,
                    date_str=date_str,
                    movie_title="Spider-Man",
                    reason=f"HTTP {status_code} server error",
                    error=f"HTTP_{status_code}"
                )

            if status_code != 200:
                return CheckResult(
                    url=url,
                    is_available=False,
                    status_code=status_code,
                    final_url=final_url,
                    date_str=date_str,
                    movie_title="Spider-Man",
                    reason=f"HTTP {status_code} unexpected response code",
                    error=f"HTTP_{status_code}"
                )

            # Check 1: Final URL redirection check & Target Date Code validation
            original_code = url.strip("/").split("/")[-1]
            if "buytickets" not in final_url:
                logger.info(f"URL redirected away from ticket booking page: {final_url}")
                return CheckResult(
                    url=url,
                    is_available=False,
                    status_code=status_code,
                    final_url=final_url,
                    date_str=date_str,
                    movie_title="Spider-Man",
                    reason="Redirected away from booking page",
                )

            # If target URL specifies a date code (e.g. 20260731), ensure final_url still points to the same date code
            if original_code.isdigit() and len(original_code) == 8:
                if original_code not in final_url:
                    logger.info(f"BookMyShow redirected target date [{original_code}] to fallback date page [{final_url}]")
                    return CheckResult(
                        url=url,
                        is_available=False,
                        status_code=status_code,
                        final_url=final_url,
                        date_str=date_str,
                        movie_title="Spider-Man",
                        reason=f"Bookings for {date_str} not open yet (redirected to current date)",
                    )

            # Parse HTML content
            soup = BeautifulSoup(response.text, "html.parser")
            movie_title = self.parse_movie_title(soup, url)
            page_text = response.text.lower()

            # Check 2: Negative availability indicators
            unavailability_keywords = [
                "no shows available",
                "currently unavailable",
                "shows unavailable for this date",
                "bookings not open",
                "tickets not available",
                "page not found",
                "we couldn't find the page",
                "something went wrong",
            ]
            for kw in unavailability_keywords:
                if kw in page_text:
                    return CheckResult(
                        url=url,
                        is_available=False,
                        status_code=status_code,
                        final_url=final_url,
                        date_str=date_str,
                        movie_title=movie_title,
                        reason=f"Unavailability keyword found: '{kw}'",
                    )

            # Check 3: Positive availability indicators
            showtime_elements = soup.select(
                ".showtime-pill, .time-pill, .showtimes, .php-showtime, "
                "[data-showtime], a[href*='seat-layout'], button[data-session-id], "
                ".btn-tickets, .seat-plan, div[class*='showtime'], div[class*='Session']"
            )

            if len(showtime_elements) > 0:
                return CheckResult(
                    url=url,
                    is_available=True,
                    status_code=status_code,
                    final_url=final_url,
                    date_str=date_str,
                    movie_title=movie_title,
                    reason=f"Found {len(showtime_elements)} showtime/booking elements",
                )

            # Check 4: Inspect Next.js __NEXT_DATA__ JSON payload if present
            next_data_script = soup.find("script", id="__NEXT_DATA__")
            if next_data_script and next_data_script.string:
                json_content = next_data_script.string.lower()
                if "showtime" in json_content or "sessionid" in json_content:
                    if "isavailable\":true" in json_content or "\"available\":true" in json_content:
                        return CheckResult(
                            url=url,
                            is_available=True,
                            status_code=status_code,
                            final_url=final_url,
                            date_str=date_str,
                            movie_title=movie_title,
                            reason="Found available showtimes in embedded JSON data",
                        )

            # Check 5: General fallback indicator
            time_pattern = re.compile(r"\b(1[0-2]|0?[1-9]):[0-5][0-9]\s*(AM|PM)\b", re.IGNORECASE)
            time_matches = time_pattern.findall(response.text)
            if len(time_matches) >= 2:
                return CheckResult(
                    url=url,
                    is_available=True,
                    status_code=status_code,
                    final_url=final_url,
                    date_str=date_str,
                    movie_title=movie_title,
                    reason=f"Found {len(time_matches)} showtime timestamps on page",
                )

            return CheckResult(
                url=url,
                is_available=False,
                status_code=status_code,
                final_url=final_url,
                date_str=date_str,
                movie_title=movie_title,
                reason="No active showtimes or booking buttons detected",
            )

        except Exception as e:
            logger.error(f"Network error checking {url}: {e}")
            return CheckResult(
                url=url,
                is_available=False,
                status_code=0,
                final_url=url,
                date_str=date_str,
                movie_title="Spider-Man",
                reason=f"Network error: {str(e)}",
                error=str(e),
            )

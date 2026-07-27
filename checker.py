import re
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Optional
import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

logger = logging.getLogger("BookMyShowMonitor")

# Realistic desktop Chrome browser headers
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
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
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
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
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._init_scraper()

    def _init_scraper(self):
        """Initializes cloudscraper to bypass Cloudflare 403 anti-bot challenges"""
        if HAS_CLOUDSCRAPER:
            try:
                self.session = cloudscraper.create_scraper(
                    browser={
                        "browser": "chrome",
                        "platform": "windows",
                        "desktop": True,
                    }
                )
                logger.info("Cloudscraper initialized to bypass Cloudflare 403 blocks.")
            except Exception as e:
                logger.warning(f"Cloudscraper init fallback to requests.Session: {e}")
                self.session = requests.Session()
        else:
            self.session = requests.Session()

        self.session.headers.update(DEFAULT_HEADERS)
        self.warmed_up = False

    def warmup_session(self):
        """Hits BookMyShow home page to acquire session cookies"""
        try:
            logger.info("Warming up BookMyShow session cookies...")
            self.session.get("https://in.bookmyshow.com/", timeout=self.timeout)
            self.warmed_up = True
        except Exception as e:
            logger.debug(f"Warmup warning: {e}")

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

    def check_url(self, url: str) -> CheckResult:
        date_str = self.parse_date_from_url(url)
        logger.info(f"Checking URL for date [{date_str}]: {url}")

        if not self.warmed_up:
            self.warmup_session()

        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True
            )

            # Retry once with fresh scraper if 403 occurs
            if response.status_code == 403:
                logger.info(f"Received 403 for [{date_str}]. Re-initializing scraper session...")
                self._init_scraper()
                self.warmup_session()
                response = self.session.get(url, timeout=self.timeout, allow_redirects=True)

            status_code = response.status_code
            final_url = response.url

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

            # Check 1: Final URL redirection check
            original_code = url.strip("/").split("/")[-1]
            if "buytickets" not in final_url and original_code not in final_url:
                logger.info(f"URL redirected away from ticket booking: {final_url}")
                return CheckResult(
                    url=url,
                    is_available=False,
                    status_code=status_code,
                    final_url=final_url,
                    date_str=date_str,
                    movie_title="Spider-Man",
                    reason="Redirected away from booking page",
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

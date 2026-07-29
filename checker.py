import re
import json
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

# Perfectly matched Desktop Chrome 124 Headers
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
        """Extract date from URL like 20260801 or fromdate=2026-08-01 -> 1 Aug"""
        match = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", url)
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
        return "1 Aug"

    def parse_movie_title(self, soup: Optional[BeautifulSoup], url: str) -> str:
        """Extract movie title from environment, page title, or fallback default"""
        import os
        custom_title = os.getenv("MOVIE_TITLE")
        if custom_title:
            return custom_title

        if soup and soup.title and soup.title.string:
            title_text = soup.title.string.strip()
            title_clean = re.sub(
                r"\s*\|\s*(BookMyShow|District|PVR|Movie Tickets|Showtimes|Cinema).*$",
                "",
                title_text,
                flags=re.IGNORECASE,
            ).strip()
            if title_clean and "inox" not in title_clean.lower() and "cinema" not in title_clean.lower():
                return title_clean

        return "Spider-Man: Brand New Day (3D)"

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
            # PVR Cinemas Platform Specific Verification (Direct Backend API Query)
            if "pvrcinemas" in url:
                try:
                    pvr_headers = {
                        "User-Agent": DESKTOP_CHROME_HEADERS["User-Agent"],
                        "Accept": "application/json, text/plain, */*",
                        "Content-Type": "application/json",
                        "Origin": "https://www.pvrcinemas.com",
                        "Referer": url,
                        "chain": "INOX",
                        "city": "Chennai",
                        "appVersion": "1.0",
                        "platform": "WEB",
                        "country": "INDIA",
                    }
                    pvr_payload = {"cid": "232", "lat": "0.000", "lng": "0.000"}

                    if HAS_CURL_CFFI:
                        api_res = curl_requests.post(
                            "https://api3.pvrcinemas.com/api/v1/booking/content/csessions",
                            json=pvr_payload,
                            headers=pvr_headers,
                            impersonate="chrome124",
                            timeout=self.timeout
                        )
                    else:
                        api_res = requests.post(
                            "https://api3.pvrcinemas.com/api/v1/booking/content/csessions",
                            json=pvr_payload,
                            headers=pvr_headers,
                            timeout=self.timeout
                        )

                    if api_res.status_code == 200:
                        api_data = api_res.json()
                        out = api_data.get("output", {}) or {}
                        cinema_movies = out.get("cinemaMovieSessions", [])

                        spiderman_shows = []
                        for item in cinema_movies:
                            m_info = item.get("movieRe", {})
                            movie_name = (m_info.get("filmName") or "").upper()
                            if "SPIDER" in movie_name or "SPIDER-MAN" in movie_name:
                                films = m_info.get("films", [])
                                for f in films:
                                    shows = f.get("shows", [])
                                    for s in shows:
                                        show_date = str(s.get("showTime") or s.get("date") or "")
                                        if "2026-08-01" in show_date or "01 Aug" in show_date or "1 Aug" in show_date:
                                            spiderman_shows.append(s)

                        if len(spiderman_shows) > 0:
                            return CheckResult(
                                url=url,
                                is_available=True,
                                status_code=200,
                                final_url=url,
                                date_str=date_str,
                                movie_title="Spider-Man",
                                reason=f"SPIDER-MAN 1 AUG SHOWTIMES LIVE ON PVR! Found {len(spiderman_shows)} active shows!",
                            )
                        else:
                            return CheckResult(
                                url=url,
                                is_available=False,
                                status_code=200,
                                final_url=url,
                                date_str=date_str,
                                movie_title="Spider-Man",
                                reason="PVR Cinemas: Spider-Man 1 Aug shows not added yet (Only 29-31 Jul listed)",
                            )
                except Exception as e:
                    logger.warning(f"PVR API check error: {e}")

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

            # Check 1: Final URL redirection check
            original_code = url.strip("/").split("/")[-1]
            if "buytickets" not in final_url and "seat-layout" not in final_url and "district.in" not in final_url and "pvrcinemas" not in final_url:
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

            # Parse HTML content
            soup = BeautifulSoup(response.text, "html.parser")
            movie_title = self.parse_movie_title(soup, url)
            page_text = response.text.lower()

            # District.in Platform Specific Seat Map Verification
            if "district.in" in url or "district.in" in final_url:
                # Check 1: Explicit closed text indicators on District.in
                district_closed_keywords = [
                    "booking is now closed",
                    "booking window for this show has closed",
                    "sorry! booking is now closed",
                    "booking is closed",
                    "show has closed",
                ]
                for kw in district_closed_keywords:
                    if kw in page_text:
                        logger.info(f"District.in closed keyword detected: '{kw}'")
                        return CheckResult(
                            url=url,
                            is_available=False,
                            status_code=status_code,
                            final_url=final_url,
                            date_str=date_str,
                            movie_title=movie_title,
                            reason=f"District.in seat section not activated yet ('{kw}')",
                        )

                next_data_script = soup.find("script", id="__NEXT_DATA__")
                if next_data_script and next_data_script.string:
                    try:
                        data = json.loads(next_data_script.string)
                        page_props = data.get("props", {}).get("pageProps", {})
                        if not page_props or page_props.get("isError") or not any(k in str(page_props).lower() for k in ["seat", "grid", "categories", "layout"]):
                            logger.info("District.in seat layout pageProps is empty or inactive.")
                            return CheckResult(
                                url=url,
                                is_available=False,
                                status_code=status_code,
                                final_url=final_url,
                                date_str=date_str,
                                movie_title=movie_title,
                                reason="District.in seat section not activated yet (Waiting for seat map release)",
                            )
                        else:
                            return CheckResult(
                                url=url,
                                is_available=True,
                                status_code=status_code,
                                final_url=final_url,
                                date_str=date_str,
                                movie_title=movie_title,
                                reason="SEAT MAP ACTIVATED ON DISTRICT.IN! Seats are live for selection!",
                            )
                    except Exception as e:
                        logger.warning(f"District.in JSON parse error: {e}")

            # Check 2: Unavailability & Error Page indicators for BookMyShow
            unavailability_keywords = [
                "something is not right",
                "connectivity issue with the cinema",
                "proceed with another cinema",
                "facing some connectivity issue",
                "error (#5)",
                "(#5)",
                "#5",
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
                    logger.info(f"Unavailability/error page keyword detected: '{kw}'")
                    return CheckResult(
                        url=url,
                        is_available=False,
                        status_code=status_code,
                        final_url=final_url,
                        date_str=date_str,
                        movie_title=movie_title,
                        reason=f"Seat section not activated yet (Showing '#5' error refresh page)",
                    )

            # Check 3: Direct Seat-Layout URL Strict Verification for BookMyShow
            if "seat-layout" in final_url or "seat-layout" in url:
                active_seat_keywords = [
                    "seatlayoutdata",
                    "seatmap",
                    "categories",
                    "availableseats",
                    "seat-container",
                    "seat-matrix",
                    "data-seat-id",
                    "ticket-picker",
                ]
                has_active_seat_data = any(k in page_text for k in active_seat_keywords)

                if has_active_seat_data:
                    return CheckResult(
                        url=url,
                        is_available=True,
                        status_code=status_code,
                        final_url=final_url,
                        date_str=date_str,
                        movie_title=movie_title,
                        reason="SEAT LAYOUT ACTIVATED! Seat selection section is live!",
                    )
                else:
                    logger.info("Seat layout page loaded but active seat payload is missing.")
                    return CheckResult(
                        url=url,
                        is_available=False,
                        status_code=status_code,
                        final_url=final_url,
                        date_str=date_str,
                        movie_title=movie_title,
                        reason="Seat section not activated yet (Showing '#5' error refresh page)",
                    )

            # Check 4: Positive showtime availability indicators on buytickets page
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

            return CheckResult(
                url=url,
                is_available=False,
                status_code=status_code,
                final_url=final_url,
                date_str=date_str,
                movie_title=movie_title,
                reason="No active showtimes or seat section detected",
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

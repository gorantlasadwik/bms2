# 🎟️ BookMyShow 24/7 Ticket Monitor & Fast2SMS Notifier

A 24/7 continuous background monitoring service built in Python for BookMyShow movie/event ticket availability. Automatically sends instant **SMS alerts** via **Fast2SMS** (and optional **ntfy.sh** push notifications) within seconds of bookings going live.

Designed for deployment as a **Render Background Worker** with built-in **Anti-Sleep Keepalive Activator**, rate-limit backoff, and deduplication logic.

---

## 🏗️ Architecture Overview

```
                      Render Background Worker
                                 │
                          Every 30 seconds
                                 │
            ┌────────────────────┼────────────────────┐
            │                    │                    │
         30 Jul               31 Jul                1 Aug
            │                    │                    │
            └────────────────────┬────────────────────┘
                                 │
                   Detect booking page is live
            (URL redirect, showtime pills, JSON data)
                                 │
                           Fast2SMS API
                                 │
                        📱 Your Mobile Phone
```

---

## 🛠️ Tech Stack

- **Python 3.12**
- **Requests**: HTTP client with custom desktop browser headers & session handling.
- **BeautifulSoup4**: HTML structure parsing and showtimes extraction.
- **Fast2SMS API**: Instant SMS dispatcher to Indian numbers (+91).
- **ntfy.sh**: High-priority push notifications (optional).
- **python-dotenv**: Environment variable loader.
- **Render Deployment**: Continuous Background Worker Blueprint.

---

## 🧠 Smart Detection & Reliability Features

1. **Smarter Availability Detection**:
   - Detects if the final URL redirects away from `buytickets` (e.g. back to cinema page or home page).
   - Scans HTML for active showtime pills, seat layout links, and booking buttons.
   - Parses embedded Next.js JSON data (`__NEXT_DATA__`) for ticket availability state.
   - Filters out false alarms (e.g. pages stating "no shows available" or "currently unavailable").

2. **Duplicate Prevention**:
   - Once an alert is sent for a specific URL, no further SMS messages are sent for that date unless the state changes back and forth.

3. **Anti-Sleep Activator**:
   - Render Free tier services enter sleep mode after 15 minutes of HTTP inactivity.
   - Includes an embedded background HTTP health server (`http.server`) listening on `$PORT` alongside a self-ping timer thread to guarantee continuous 24/7 uptime.

4. **Rate-Limit Protection & Retries**:
   - Rotates realistic desktop Chrome User-Agent and browser headers.
   - Automatically backs off check interval if HTTP 429/403 rate-limiting occurs.
   - Graceful network timeout (10 seconds) with retries.

---

## 📁 Project Structure

```
bookmyshow-monitor/
│
├── app.py           # Main loop, anti-sleep server, deduplication
├── checker.py       # BookMyShow scraping & smart availability detection
├── notifier.py      # Fast2SMS and ntfy push notification handler
├── requirements.txt # Python dependencies
├── render.yaml      # Render Background Worker Blueprint configuration
├── .env             # Local environment variables (excluded from git)
├── .gitignore       # Git ignore rules
└── README.md        # Documentation
```

---

## 🚀 Quick Setup & Local Running

### 1. Prerequisites
- Python 3.10+ installed.
- A Fast2SMS account (`fast2sms.com`).

### 2. Local Installation
```bash
pip install -r requirements.txt
```

### 3. Environment Configuration
Create or edit `.env`:

```env
FAST2SMS_API_KEY=your_fast2sms_api_key_here
FAST2SMS_NUMBER=9618595425
CHECK_INTERVAL=30
NTFY_TOPIC=sadwik_bms_alerts
NTFY_TOKEN=your_ntfy_token_here
```

### 4. Run Locally
```bash
python app.py
```

---

## ☁️ Deployment on Render (24/7 Free Hosting)

### 1. Push Code to GitHub
Push your repository to GitHub (`https://github.com/gorantlasadwik/bms2.git`).

### 2. Connect to Render
1. Log in to [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** -> **Blueprint**.
3. Connect your GitHub repository (`bms2`).
4. Render will detect `render.yaml` automatically as a **Background Worker**.

### 3. Environment Variables in Render Dashboard
Add the following in Render:

| Key | Description | Example |
|---|---|---|
| `FAST2SMS_API_KEY` | Fast2SMS Developer API Key | `D5EX1tbYk...` |
| `FAST2SMS_NUMBER` | Recipient 10-digit mobile number | `9618595425` |
| `CHECK_INTERVAL` | Seconds between checks | `30` |
| `NTFY_TOPIC` | *(Optional)* ntfy.sh topic | `sadwik_bms_alerts` |
| `NTFY_TOKEN` | *(Optional)* ntfy.sh Bearer Token | `tk_j3n...` |

---

## 📨 SMS Alert Message Example

When tickets go live, an SMS is sent to your phone:

```text
ALERT: Spider-Man bookings LIVE for 31 Jul! Open BookMyShow: https://in.bookmyshow.com/...
```

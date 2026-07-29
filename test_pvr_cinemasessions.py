from curl_cffi import requests
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.pvrcinemas.com/",
    "Origin": "https://www.pvrcinemas.com",
    "client": "WEB",
}

urls = [
    "https://pvravatar.pvrcinemas.com/v1/booking/content/cinemasessions?cid=232",
    "https://pvravatar.pvrcinemas.com/v1/booking/content/cinemasessions?cinemaId=232",
    "https://www.pvrcinemas.com/pvravatar/v1/booking/content/cinemasessions?cid=232",
    "https://pvravatar.pvrcinemas.com/v1/booking/content/cinemasessions?city=Chennai&cid=232",
    "https://pvravatar.pvrcinemas.com/v1/booking/content/cinemasessions?cid=232&city=Chennai",
]

for url in urls:
    try:
        r = requests.get(url, headers=headers, impersonate="chrome124", timeout=10)
        print(f"URL: {url}")
        print(f"  Status: {r.status_code}, Len: {len(r.text)}")
        print(f"  Snippet: {repr(r.text[:300])}")
    except Exception as e:
        print(f"  Error: {e}")

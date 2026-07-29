from curl_cffi import requests
import re

url = 'https://www.pvrcinemas.com/cinemasessions/Chennai/INOX-The-Marina-Mall,-OMR,-Chennai/232'
r = requests.get(url, impersonate='chrome124')

# Find JS scripts
scripts = re.findall(r'src=["\'](.*?.js.*?)["\']', r.text)
print("JS scripts found:", scripts)

for js_path in scripts:
    if js_path.startswith('/'):
        js_url = 'https://www.pvrcinemas.com' + js_path
    else:
        js_url = js_path

    print(f"Fetching JS: {js_url}")
    try:
        res = requests.get(js_url, impersonate='chrome124', timeout=10)
        print(f"  Status: {res.status_code}, Len: {len(res.text)}")
        # Search for API endpoints
        apis = re.findall(r'["\'](/pvravatar/[^"\']+)["\']', res.text)
        apis += re.findall(r'["\'](https?://[^"\']*pvrcinemas[^"\']*)["\']', res.text)
        if apis:
            print("  Found APIs:", list(set(apis))[:15])
    except Exception as e:
        print(f"  Error: {e}")

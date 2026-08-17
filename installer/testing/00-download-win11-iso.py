#!/usr/bin/env python3
"""Download the official Windows 11 x64 multi-edition ISO straight from Microsoft,
without going through the interactive software-download page.

Replays the same internal API calls the page's own JavaScript makes (session
whitelisting via vlscppe.microsoft.com, an anti-bot handshake via
ov-df.microsoft.com, then the software-download-connector API for the real,
time-limited download link) - this is the same technique the well-known
open-source tool Fido (https://github.com/pbatard/Fido) uses, ported to plain
Python since Fido's own command-line mode explicitly refuses to run on
non-Windows platforms (checked directly in its source), even though none of
the underlying HTTP calls are Windows-specific.

The returned download link is only valid for a limited time (Microsoft's own
design, not something this script controls) - the download starts immediately
after it's obtained, it is never just printed and left for later.

Usage:
    ./00-download-win11-iso.py [--lang French] [--out win11.iso]
"""
import argparse
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

# These IDs are read directly out of Fido's own $WindowsVersions/$OrgId/$ProfileId/
# $InstanceId tables (see Fido.ps1) - not guessed. EDITION_ID is Fido's "Windows 11
# Home/Pro/Edu" x64 entry for its current listed release; the multi-edition ISO lets
# you pick the actual edition (Home/Pro/etc.) from a product key or menu at install
# time, same as the official download page's own default option.
ORG_ID = "y6jn8c31"
PROFILE_ID = "606624d44113"
INSTANCE_ID = "560dc9f3-1aa5-4a2f-b63c-9e18f8d0e175"
EDITION_ID = 3321
REFERER = "https://www.microsoft.com/software-download/windows11"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0.0.0 Safari/537.36")
TIMEOUT = 30


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url, headers=None):
    import json
    return json.loads(fetch(url, headers))


def whitelist_session(session_id):
    fetch(f"https://vlscppe.microsoft.com/tags?org_id={ORG_ID}&session_id={session_id}")


def anti_bot_handshake(session_id):
    mdt_url = (f"https://ov-df.microsoft.com/mdt.js?instanceId={INSTANCE_ID}"
               f"&PageId=si&session_id={session_id}")
    body = fetch(mdt_url)
    w_match = re.search(r"[?&]w=([A-F0-9]+)", body)
    rticks_match = re.search(r"rticks\=\"?\+?(\d+)", body)
    if not w_match or not rticks_match:
        raise RuntimeError("Could not extract w/rticks from ov-df.microsoft.com's anti-bot "
                            "challenge - Microsoft likely changed this flow, check Fido's "
                            "current source for the up-to-date sequence.")
    w, rticks = w_match.group(1), rticks_match.group(1)
    epoch_ms = int(time.time() * 1000)
    reply_url = (f"https://ov-df.microsoft.com/?session_id={session_id}"
                 f"&CustomerId={INSTANCE_ID}&PageId=si&w={w}&mdt={epoch_ms}&rticks={rticks}")
    fetch(reply_url)


def get_sku_id(session_id, lang):
    url = ("https://www.microsoft.com/software-download-connector/api/"
           f"getskuinformationbyproductedition?profile={PROFILE_ID}"
           f"&productEditionId={EDITION_ID}&SKU=undefined&friendlyFileName=undefined"
           f"&Locale=en-US&sessionID={session_id}")
    for attempt in range(3):
        if attempt:
            time.sleep(2)
        data = fetch_json(url)
        if data.get("Errors"):
            continue
        skus = data.get("Skus", [])
        if not skus:
            continue
        for sku in skus:
            if lang.lower() in sku["LocalizedLanguage"].lower() or lang.lower() in sku["Language"].lower():
                return sku["Id"], sku["LocalizedLanguage"]
        # Fall back to the first available language if the requested one isn't listed.
        return skus[0]["Id"], skus[0]["LocalizedLanguage"]
    raise RuntimeError("Could not retrieve SKU/language list from Microsoft's API.")


def get_download_url(session_id, sku_id):
    url = ("https://www.microsoft.com/software-download-connector/api/"
           f"GetProductDownloadLinksBySku?profile={PROFILE_ID}&productEditionId=undefined"
           f"&SKU={sku_id}&friendlyFileName=undefined&Locale=en-US&sessionID={session_id}")
    data = fetch_json(url, headers={"Referer": REFERER})
    if data.get("Errors"):
        raise RuntimeError(f"Microsoft API error: {data['Errors'][0].get('Value')}")
    for option in data.get("ProductDownloadOptions", []):
        if option.get("DownloadType") == 1:  # 1 == x64, per Fido's Get-Arch-From-Type
            return option["Uri"]
    raise RuntimeError("No x64 download option in the API response.")


def download(url, out_path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        written = 0
        chunk = 1024 * 1024
        with open(out_path, "wb") as f:
            while True:
                data = resp.read(chunk)
                if not data:
                    break
                f.write(data)
                written += len(data)
                if total:
                    pct = written * 100 // total
                    print(f"\r{out_path}: {written // (1024*1024)} MiB / "
                          f"{total // (1024*1024)} MiB ({pct}%)", end="", flush=True)
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", default="French", help="Language to request (default: French)")
    parser.add_argument("--out", default="win11.iso", help="Output file path")
    args = parser.parse_args()

    session_id = str(uuid.uuid4())
    print(f"Session: {session_id}")

    print("Whitelisting session with vlscppe.microsoft.com...")
    whitelist_session(session_id)

    print("Completing ov-df.microsoft.com anti-bot handshake...")
    anti_bot_handshake(session_id)

    print(f"Looking up SKU for language '{args.lang}'...")
    sku_id, resolved_lang = get_sku_id(session_id, args.lang)
    print(f"Resolved language: {resolved_lang} (SKU {sku_id})")

    print("Requesting the real, time-limited download link...")
    url = get_download_url(session_id, sku_id)
    print(f"Download URL (time-limited, downloading now): {url}")

    download(url, args.out)
    print(f"Done: {args.out}")


if __name__ == "__main__":
    try:
        main()
    except (urllib.error.URLError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

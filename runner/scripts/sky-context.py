#!/usr/bin/env python3
"""sky-context.py — Moon phase, sunrise, sunset, day length for wake.sh

Usage: sky-context.py [location]

Outputs lines prefixed with "- " for direct injection into the wake prompt.
Fails silently: all errors produce a single unavailable line.
"""

import sys
import json
import datetime
import urllib.request
import urllib.parse


def moon_phase(date: datetime.date) -> str:
    """Return moon phase name and days into cycle, computed from Julian Day."""
    y, m, d = date.year, date.month, date.day
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5

    # Reference: new moon on 2000-01-06 at ~18:14 UTC ≈ JD 2451550.26
    known_new_jd = 2451550.26
    cycle_days = 29.53058867

    phase_days = (jd - known_new_jd) % cycle_days
    phase_frac = phase_days / cycle_days

    if phase_frac < 0.0625:
        name = "New Moon"
    elif phase_frac < 0.1875:
        name = "Waxing Crescent"
    elif phase_frac < 0.3125:
        name = "First Quarter"
    elif phase_frac < 0.4375:
        name = "Waxing Gibbous"
    elif phase_frac < 0.5625:
        name = "Full Moon"
    elif phase_frac < 0.6875:
        name = "Waning Gibbous"
    elif phase_frac < 0.8125:
        name = "Last Quarter"
    elif phase_frac < 0.9375:
        name = "Waning Crescent"
    else:
        name = "New Moon"

    return f"{name} ({phase_days:.0f}d into cycle)"


def parse_time(s: str) -> datetime.datetime | None:
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def day_length_minutes(sunrise: str, sunset: str) -> int | None:
    sr = parse_time(sunrise)
    ss = parse_time(sunset)
    if sr is None or ss is None:
        return None
    return (ss - sr).seconds // 60


def format_length(total_minutes: int) -> str:
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m}m"


def fetch_astronomy(location: str) -> dict | None:
    encoded = urllib.parse.quote(location)
    url = f"https://wttr.in/{encoded}?format=j1"
    req = urllib.request.Request(url, headers={"User-Agent": "sky-context/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    return data


def main() -> None:
    location = sys.argv[1].strip() if len(sys.argv) > 1 else ""

    # Moon phase — always available, no network needed
    print(f"- Moon: {moon_phase(datetime.date.today())}")

    if not location:
        print("- Sunrise/Sunset: unavailable (no location set)")
        return

    try:
        data = fetch_astronomy(location)
        today = data["weather"][0]["astronomy"][0]
        sunrise = today["sunrise"]
        sunset = today["sunset"]
        print(f"- Sunrise: {sunrise}  Sunset: {sunset}")

        today_mins = day_length_minutes(sunrise, sunset)
        if today_mins is not None:
            trend = ""
            try:
                tomorrow = data["weather"][1]["astronomy"][0]
                tomorrow_mins = day_length_minutes(
                    tomorrow["sunrise"], tomorrow["sunset"]
                )
                if tomorrow_mins is not None:
                    diff = tomorrow_mins - today_mins
                    if diff > 0:
                        trend = f", lengthening (+{diff}m/day)"
                    elif diff < 0:
                        trend = f", shortening ({diff}m/day)"
            except (KeyError, IndexError):
                pass
            print(f"- Day length: {format_length(today_mins)}{trend}")

    except Exception:
        print("- Sunrise/Sunset: unavailable")


if __name__ == "__main__":
    main()

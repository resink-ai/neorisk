"""Synthetic modern devices: real browser configurations from intoli/user-agents (user-agent,
platform, vendor, screen, viewport, connection, weighted by real traffic) plus simulated device
hardware, network (ISP / mobile carrier / VPN), battery and behaviour over time.

The point is not realism of every number but having the attributes FP-Stalker lacks (battery,
VPN, connection, hardware hints) with a known device identity, including the hard case of
many devices sharing one popular configuration. Results on it test the pipeline and the drift
model written here, not the real world.

Per device, observed 1..N times over 180 days:
  stable    hardware (cores, memory, GPU, touch points), fonts, timezone, languages, home
            ISP and its /24 prefix; canvas and audio hashes come from the rendering stack
            (GPU, OS, engine), so devices with the same stack share them
  drifting  browser version (+1 major about every 30 days), viewport (desktop window size),
            connection type and speed, battery level and charging (every observation), IP
            host and sometimes the network (home / mobile carrier / VPN), rare font installs
  spoofers  10% of devices run an anti-detect setup: each observation takes a fresh
            user-agent, platform and canvas hash, and most go through a VPN
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from devicefp.profiles import Field, Profiles, languages, ua_words

T0 = datetime(2026, 1, 1)
DAYS = 180

FONTS = {
    "win": ["Arial", "Calibri", "Cambria", "Consolas", "Courier New", "Georgia", "Segoe UI",
            "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana", "Segoe UI Emoji",
            "Microsoft YaHei", "MS Gothic", "Malgun Gothic", "Leelawadee UI", "Gabriola",
            "Franklin Gothic", "Bahnschrift", "Ink Free"],
    "mac": ["Helvetica Neue", "Menlo", "Monaco", "Avenir", "Futura", "Gill Sans", "Optima",
            "Palatino", "PingFang SC", "Hiragino Sans", "Apple Color Emoji", "Arial",
            "Times New Roman", "Courier New", "Georgia", "Verdana", "SF Pro", "Baskerville"],
    "linux": ["DejaVu Sans", "DejaVu Serif", "Liberation Sans", "Liberation Mono", "Noto Sans",
              "Noto Color Emoji", "Ubuntu", "Cantarell", "Roboto", "Droid Sans", "FreeSans"],
    "android": ["Roboto", "Noto Sans", "Noto Color Emoji", "Droid Sans Mono", "Cutive Mono",
                "Coming Soon", "Dancing Script", "Carrois Gothic", "Samsung Sans"],
    "ios": ["Helvetica Neue", "Apple Color Emoji", "Avenir", "Menlo", "Georgia", "Arial",
            "Times New Roman", "Courier New", "PingFang SC", "Hiragino Sans"],
}
EXTRA_FONTS = ["Adobe Garamond", "Fira Code", "JetBrains Mono", "Source Code Pro", "Lato",
               "Open Sans", "Montserrat", "Raleway", "Comic Neue", "Inter", "IBM Plex Sans",
               "Office Symbol", "Wingdings 3", "Bookman Old Style", "Century Gothic"]
GPUS = {
    "win": ["ANGLE (NVIDIA GeForce RTX 3060)", "ANGLE (NVIDIA GeForce GTX 1650)",
            "ANGLE (Intel UHD Graphics 620)", "ANGLE (Intel Iris Xe Graphics)",
            "ANGLE (AMD Radeon RX 6600)", "ANGLE (AMD Radeon Graphics)"],
    "mac": ["Apple M1", "Apple M2", "Apple M3", "Intel Iris Plus Graphics", "Apple M1 Pro"],
    "linux": ["Mesa Intel UHD Graphics 630", "NVIDIA GeForce GTX 1060/PCIe/SSE2",
              "AMD Radeon RX 580 (radeonsi)", "llvmpipe (LLVM 15.0.7)"],
    "android": ["Adreno (TM) 740", "Adreno (TM) 650", "Mali-G78", "Mali-G710", "Adreno (TM) 619",
                "PowerVR Rogue GE8320"],
    "ios": ["Apple GPU"],
}
# (country, timezone offset minutes, home ISP ASNs, mobile carrier ASNs, languages)
REGIONS = [
    ("US", [300, 360, 420, 480], [7922, 7018, 701, 20115, 22773], [21928, 6167, 20057],
     ["en-US"]),
    ("GB", [0], [2856, 5089, 13285], [12576, 25135], ["en-GB"]),
    ("DE", [-60], [3320, 3209, 6805], [3320, 6805], ["de-DE", "en-US"]),
    ("FR", [-60], [3215, 12322, 5410], [3215, 51207], ["fr-FR", "en-US"]),
    ("BR", [180], [28573, 18881, 26599], [26615, 28573], ["pt-BR"]),
    ("IN", [-330], [9829, 24560, 45609], [55836, 45609], ["en-IN", "hi-IN"]),
    ("JP", [-540], [4713, 2516, 17676], [2516, 9605], ["ja-JP"]),
    ("CN", [-480], [4134, 4837, 9808], [9808, 56046], ["zh-CN"]),
]
REGION_P = np.array([0.30, 0.08, 0.08, 0.07, 0.10, 0.15, 0.07, 0.15])
VPN_ASNS = [9009, 212238, 60068, 16276, 14061, 24940, 20473, 397423]   # VPN/hosting networks
VPN_COUNTRIES = ["US", "NL", "DE", "GB", "SG", "CH", "SE", "JP"]
CONN = {"mobile": ["4g", "4g", "4g", "3g", "wifi", "wifi"], "desktop": ["wifi", "ethernet"]}


def consistent(ua: str, platform: str, category: str, screen: str) -> bool:
    """intoli keeps every configuration it sees, including impossible ones (an iPhone
    user-agent on platform "Linux x86_64", a desktop Chrome at 375x812: emulators and bots).
    Normal synthetic devices start from the consistent ones only."""
    mobile_ua = "iPhone" in ua or "iPad" in ua or "Android" in ua
    mobile_platform = platform in ("iPhone", "iPad") or platform.startswith(
        ("Linux arm", "Linux aarch64"))
    width = int(screen.split("x")[0])
    if mobile_ua != mobile_platform or mobile_ua != (category != "desktop"):
        return False
    return width < 1024 if mobile_ua else width >= 1024


def load_intoli(path: Path) -> pl.DataFrame:
    """intoli/user-agents records, consistent ones only (see `consistent`)."""
    rows = json.loads(path.read_text())
    out = []
    for r in rows:
        c = r.get("connection") or {}
        out.append({"user_agent": r["userAgent"], "platform": r["platform"],
                    "vendor": r["vendor"], "category": r["deviceCategory"],
                    "screen": f"{r['screenWidth']}x{r['screenHeight']}",
                    "viewport": f"{r['viewportWidth']}x{r['viewportHeight']}",
                    "language": r["language"], "plugins_length": r["pluginsLength"],
                    "effective_type": c.get("effectiveType", ""), "weight": r["weight"]})
    t = pl.DataFrame(out)
    return t.filter(pl.Series([consistent(*r) for r in t.select(
        "user_agent", "platform", "category", "screen").iter_rows()]))


def _os(ua: str, platform: str) -> str:
    if "iPhone" in ua or "iPad" in ua:
        return "ios"
    if "Android" in ua:
        return "android"
    if "Mac" in platform:
        return "mac"
    if "Win" in platform:
        return "win"
    return "linux"


_VERSION = re.compile(r"((?:Chrome|Firefox|Edg|Version|CriOS|FxiOS|OPR)/)(\d+)")


def bump(ua: str, by: int) -> str:
    """The same browser `by` major versions later."""
    return _VERSION.sub(lambda m: f"{m.group(1)}{int(m.group(2)) + by}", ua)


def _engine(ua: str) -> str:
    return next((e for e in ("Firefox", "Edg", "Chrome", "Safari") if e in ua), "other")


def _hash(*parts) -> str:
    import hashlib

    return hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).hexdigest()


def generate(base: pl.DataFrame, devices: int = 3000, seed: int = 7,
             spoofer_share: float = 0.1) -> Profiles:
    rng = np.random.default_rng(seed)
    w = base["weight"].to_numpy()
    w = w / w.sum()
    recs = []
    for d in range(devices):
        b = base.row(int(rng.choice(len(base), p=w)), named=True)
        os_ = _os(b["user_agent"], b["platform"])
        mobile = b["category"] != "desktop"
        ri = int(rng.choice(len(REGIONS), p=REGION_P))
        country, tzs, isps, carriers, langs = REGIONS[ri]
        dev = {
            "id": f"syn-{d:05d}",
            "spoofer": rng.random() < spoofer_share,
            # Safari reports a fixed core count and no deviceMemory; Android phones of one
            # screen class mostly share a SoC
            "cores": 4 if os_ == "ios" else 8 if os_ == "android" else int(
                rng.choice([4, 8, 12, 16])),
            "memory": "na" if os_ == "ios" else int(
                rng.choice([4, 8] if mobile else [4, 8, 16, 32])),
            "gpu": str(GPUS[os_][int(_hash(b["screen"]), 16) % len(GPUS[os_])]) if mobile else str(
                rng.choice(GPUS[os_])),
            "touch": 5 if mobile else int(rng.choice([0, 0, 0, 10])),
            "fonts": sorted(set(FONTS[os_]) | set(rng.choice(
                EXTRA_FONTS, size=int(rng.choice([0] * 8 + [1, 3])) if not mobile else 0,
                replace=False))),
            "tz": int(rng.choice(tzs)),
            "langs": langs if rng.random() < 0.85 else [*langs, "en-US"],
            "isp": int(rng.choice(isps)), "carrier": int(rng.choice(carriers)),
            "home_prefix": f"{rng.integers(1, 224)}.{rng.integers(256)}.{rng.integers(256)}",
            "vpn_rate": float(rng.choice([0, 0, 0, 0, 0, 0, 0.1, 0.5, 0.9])),
            "has_battery": mobile or rng.random() < 0.6,     # laptops report a battery
            "charging_rate": float(rng.uniform(0.1, 0.6)),
            "country": country,
        }
        if dev["spoofer"]:
            dev["vpn_rate"] = 0.8
        n = 1 + int(rng.geometric(1 / 6))
        times = np.sort(rng.uniform(0, DAYS, n))
        battery = rng.uniform(0.1, 1.0)
        fonts = list(dev["fonts"])
        view = b["viewport"]
        for t in times:
            ua, platform, vendor = bump(b["user_agent"], int(t // 30)), b["platform"], b["vendor"]
            # canvas output depends on the rendering stack, not the device: GPU, OS, engine
            canvas = _hash(dev["gpu"], os_, _engine(ua), len(fonts) > len(FONTS[os_]))
            if dev["spoofer"]:
                s = base.row(int(rng.choice(len(base), p=w)), named=True)
                ua, platform, vendor = s["user_agent"], s["platform"], s["vendor"]
                canvas = _hash("noise", rng.integers(1 << 30))
            if not mobile and rng.random() < 0.3:          # window resized
                sw, sh = map(int, b["screen"].split("x"))
                view = f"{int(sw * rng.uniform(0.5, 1))}x{int(sh * rng.uniform(0.5, 0.92))}"
            if rng.random() < 0.03:                         # a font installed
                fonts = sorted(set(fonts) | {str(rng.choice(EXTRA_FONTS))})
            vpn = rng.random() < dev["vpn_rate"]
            on_mobile = mobile and not vpn and rng.random() < 0.5
            if vpn:
                asn, ip_type = int(rng.choice(VPN_ASNS)), "vpn"
                prefix = f"{rng.integers(1, 224)}.{rng.integers(256)}.{rng.integers(256)}"
                geo = str(rng.choice(VPN_COUNTRIES))
            elif on_mobile:
                asn, ip_type, geo = dev["carrier"], "mobile", dev["country"]
                prefix = f"cgnat-{dev['carrier']}-{rng.integers(64)}"
            else:
                asn, ip_type, geo = dev["isp"], "residential", dev["country"]
                prefix = dev["home_prefix"] if rng.random() < 0.9 else \
                    f"{rng.integers(1, 224)}.{rng.integers(256)}.{rng.integers(256)}"
            conn = "wifi" if ip_type == "residential" and mobile else str(
                rng.choice(CONN["mobile" if mobile else "desktop"]))
            charging = rng.random() < dev["charging_rate"]
            step = rng.uniform(0.1, 0.6) if charging else -rng.uniform(0.0, 0.35)
            battery = float(np.clip(battery + step, 0.03, 1.0))
            if battery <= 0.05:                             # recharged before the next visit
                battery = float(rng.uniform(0.5, 1.0))
            recs.append({
                "device": dev["id"], "seen_at": T0 + timedelta(days=float(t)),
                "group": "spoofer" if dev["spoofer"] else "consistent",
                "user_agent": ua, "platform": platform, "vendor": vendor,
                "device_category": b["category"], "screen": b["screen"], "viewport": view,
                "hardware_concurrency": str(dev["cores"]), "device_memory": str(dev["memory"]),
                "webgl_renderer": dev["gpu"], "max_touch_points": str(dev["touch"]),
                "canvas_hash": canvas, "audio_hash": _hash("audio", os_, dev["gpu"]),
                "timezone": str(dev["tz"]), "ip_prefix": prefix, "asn": str(asn),
                "ip_type": ip_type, "geo_country": geo, "vpn": str(vpn),
                "tz_geo_mismatch": str(geo != dev["country"]), "connection": conn,
                "downlink": str(int(rng.choice([1, 2, 5, 10]) if conn != "ethernet" else 10)),
                "battery_level": f"{round(battery * 20) * 5}" if dev["has_battery"] else "na",
                "battery_charging": str(charging) if dev["has_battery"] else "na",
                "plugins_length": str(b["plugins_length"]),
                "fonts": fonts, "ua_words": ua_words(ua),
                "languages": languages(",".join(dev["langs"])),
            })
    t = pl.DataFrame(recs).sort("seen_at", "device")
    cats = [c for c in t.columns if c not in ("device", "seen_at", "group", "fonts",
                                              "ua_words", "languages")]
    fields = tuple(Field(c, "cat") for c in cats) + tuple(
        Field(c, "set") for c in ("fonts", "ua_words", "languages"))
    return Profiles(t, fields)

#!/usr/bin/env python3
"""
android-storage-hogs-finder.py - Find out what is eating the storage on an Android phone via ADB.

Read-only: it only runs df, dumpsys diskstats, du, find and stat on the device.
Nothing is deleted.

Usage:
    python3 android-storage-hogs-finder.py                 # terminal report
    python3 android-storage-hogs-finder.py --html out.html # additionally write an HTML report
    python3 android-storage-hogs-finder.py --json out.json # additionally dump raw results
    python3 android-storage-hogs-finder.py -s SERIAL       # pick a device if several are connected
    python3 android-storage-hogs-finder.py --min-file-mb 100 --top 30
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict

SDCARD = "/storage/emulated/0"

# Known places where space silently piles up: (path relative to SDCARD, label, hint)
KNOWN_SUSPECTS = [
    ("Android/media/com.whatsapp/WhatsApp/Media", "WhatsApp media",
     "WhatsApp > Settings > Storage and data > Manage storage. Disable auto-download for groups."),
    ("Android/media/com.whatsapp/WhatsApp/Databases", "WhatsApp backups (local)",
     "Old local msgstore-*.db.crypt backups can be deleted; keep the newest."),
    ("Android/media/com.whatsapp.w4b/WhatsApp Business/Media", "WhatsApp Business media",
     "Manage storage inside WhatsApp Business."),
    ("WhatsApp/Media", "WhatsApp media (old location)", "Legacy folder from older WhatsApp versions."),
    ("Android/data/org.telegram.messenger", "Telegram cache",
     "Telegram > Settings > Data and Storage > Storage Usage > Clear cache; set a cache limit."),
    ("Telegram", "Telegram downloads", "Saved Telegram files."),
    ("Android/media/org.telegram.messenger", "Telegram media", "Telegram > Storage Usage."),
    ("Android/media/com.bambuna.podcastaddict", "Podcast Addict episodes",
     "Podcast Addict > Settings > Automatic cleanup: delete played episodes, limit episodes kept per podcast."),
    ("Android/data/au.com.shiftyjelly.pocketcasts", "Pocket Casts episodes", "Pocket Casts > Storage & data usage."),
    ("Android/data/com.spotify.music", "Spotify offline music", "Remove downloaded playlists in Spotify."),
    ("Android/data/com.google.android.youtube", "YouTube downloads", "YouTube > Library > Downloads."),
    ("Android/data/com.netflix.mediaclient", "Netflix downloads", "Netflix > Downloads."),
    ("Android/data/com.instagram.android", "Instagram cache", "Clear app cache in system settings."),
    ("Android/data/com.zhiliaoapp.musically", "TikTok cache", "TikTok > Settings > Free up space."),
    ("DCIM/.thumbnails", "Gallery thumbnails (DCIM)", "Safe to delete; regenerated on demand."),
    ("Pictures/.thumbnails", "Gallery thumbnails (Pictures)", "Safe to delete; regenerated on demand."),
    ("Download", "Downloads folder", "Often full of forgotten APKs, PDFs and videos."),
    ("Movies", "Movies folder", "Screen recordings and downloaded videos."),
    ("DCIM/Camera", "Camera photos & videos", "Back up (e.g. Google Photos) and use 'Free up space'."),
    ("Pictures/Screenshots", "Screenshots", "Usually safe to clean up."),
    ("DCIM/Screenshots", "Screenshots (DCIM)", "Usually safe to clean up."),
    ("Recordings", "Recordings", "Voice / call recordings."),
]


# --------------------------------------------------------------------------- adb helpers

class AdbError(RuntimeError):
    pass


class Adb:
    def __init__(self, serial: str | None):
        self.base = ["adb"] + (["-s", serial] if serial else [])

    def shell(self, cmd: str, timeout: int = 600) -> str:
        try:
            proc = subprocess.run(self.base + ["shell", cmd], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AdbError(f"Timeout running: {cmd}")
        return proc.stdout.decode("utf-8", errors="replace")


def pick_device(serial: str | None) -> str:
    if not shutil.which("adb"):
        sys.exit("adb not found. Install it with: brew install android-platform-tools")
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices.append((parts[0], parts[1]))
    if serial:
        devices = [d for d in devices if d[0] == serial]
    if not devices:
        sys.exit(
            "No Android device found.\n"
            "  1. Settings > About phone > tap 'Build number' 7x to enable Developer options\n"
            "  2. Settings > Developer options > enable 'USB debugging'\n"
            "  3. Connect via USB, unlock the phone and accept the 'Allow USB debugging?' prompt\n"
            "  4. Check with: adb devices"
        )
    ready = [d for d in devices if d[1] == "device"]
    if not ready:
        states = ", ".join(f"{s} ({st})" for s, st in devices)
        sys.exit(f"Device not ready: {states}\n"
                 "If 'unauthorized': unlock the phone and accept the USB debugging prompt.")
    if len(ready) > 1:
        sys.exit("Several devices connected, choose one with -s: " + ", ".join(s for s, _ in ready))
    return ready[0][0]


# --------------------------------------------------------------------------- data model

@dataclass
class AppUsage:
    package: str
    app: int = 0
    data: int = 0
    cache: int = 0

    @property
    def total(self) -> int:
        return self.app + self.data


@dataclass
class Report:
    device: dict = field(default_factory=dict)
    volumes: list = field(default_factory=list)          # [{mount,total,used,free}]
    categories: dict = field(default_factory=dict)       # diskstats category -> bytes
    apps: list = field(default_factory=list)             # [AppUsage]
    folders: dict = field(default_factory=dict)          # relpath -> bytes (du, depth <= 3)
    large_files: list = field(default_factory=list)      # [(size, mtime, path)]
    trashed: list = field(default_factory=list)          # [(size, path)]
    suspects: list = field(default_factory=list)         # [(label, rel, size, hint)]
    apks: list = field(default_factory=list)             # [(size, path)]
    tips: list = field(default_factory=list)
    scan_seconds: float = 0.0


# --------------------------------------------------------------------------- collectors

def collect_device(adb: Adb) -> dict:
    props = {}
    for key, prop in [("manufacturer", "ro.product.manufacturer"), ("model", "ro.product.model"),
                      ("android", "ro.build.version.release"), ("sdk", "ro.build.version.sdk")]:
        props[key] = adb.shell(f"getprop {prop}").strip()
    return props


def collect_df(adb: Adb) -> list:
    out = adb.shell(f"df -k /data {SDCARD} 2>/dev/null")
    vols, seen = [], set()
    for line in out.splitlines()[1:]:
        p = line.split()
        if len(p) < 6 or not p[1].isdigit():
            continue
        key = (p[1], p[2])
        if key in seen:   # /data and /storage/emulated/0 are usually the same fs
            continue
        seen.add(key)
        vols.append({"mount": p[5], "total": int(p[1]) * 1024,
                     "used": int(p[2]) * 1024, "free": int(p[3]) * 1024})
    return vols


def _json_list(text: str, key: str) -> list:
    m = re.search(rf"^{re.escape(key)}:\s*(\[.*\])\s*$", text, re.M)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return []


def collect_diskstats(adb: Adb) -> tuple[dict, list]:
    out = adb.shell("dumpsys diskstats")
    cats = {}
    for key in ["App Size", "App Data Size", "App Cache Size", "Photos Size", "Videos Size",
                "Audio Size", "Downloads Size", "System Size", "Other Size"]:
        m = re.search(rf"^{key}:\s*(\d+)", out, re.M)
        if m:
            cats[key.replace(" Size", "")] = int(m.group(1))
    names = _json_list(out, "Package Names")
    app_sizes = _json_list(out, "App Sizes")
    data_sizes = _json_list(out, "App Data Sizes")
    cache_sizes = _json_list(out, "Cache Sizes")
    apps = []
    for i, name in enumerate(names):
        apps.append(AppUsage(
            package=name,
            app=app_sizes[i] if i < len(app_sizes) else 0,
            data=data_sizes[i] if i < len(data_sizes) else 0,
            cache=cache_sizes[i] if i < len(cache_sizes) else 0,
        ))
    apps.sort(key=lambda a: a.total, reverse=True)
    return cats, apps


APK_EXT = (".apk", ".xapk", ".apks")


def collect_all_files(adb: Adb) -> list:
    """Walk the whole shared storage once: [(size, mtime, path)], largest first.

    Notes on toybox quirks seen on real devices:
      * `du` prints nothing at all for a tree that contains one unreadable folder,
      * `find -exec stat {} +` silently drops batches ("Argument list too long"),
    so we use find -print0 | xargs -n 200 stat and aggregate folder sizes ourselves.
    """
    cmd = (f"find {SDCARD}/ -type f -print0 2>/dev/null | "
           f"xargs -0 -n 200 stat -c '%s|%Y|%n' 2>/dev/null")
    out = adb.shell(cmd, timeout=1800)
    res = []
    for line in out.splitlines():
        p = line.split("|", 2)
        if len(p) == 3 and p[0].isdigit():
            res.append((int(p[0]), int(p[1]) if p[1].isdigit() else 0, p[2].replace("//", "/")))
    res.sort(reverse=True)
    return res


def rel_path(path: str) -> str:
    prefix = SDCARD.rstrip("/") + "/"
    return path[len(prefix):] if path.startswith(prefix) else path


def aggregate_folders(files: list, depth: int) -> dict:
    """Sum file sizes into every ancestor folder (relative to SDCARD) up to `depth` levels."""
    folders: dict = {}
    for size, _, path in files:
        parts = rel_path(path).split("/")[:-1]
        for i in range(1, min(len(parts), depth) + 1):
            k = "/".join(parts[:i])
            folders[k] = folders.get(k, 0) + size
    return folders


def classify_files(files: list, min_mb: int) -> tuple[list, list, list]:
    min_bytes = min_mb * 1024 ** 2
    large = [f for f in files if f[0] > min_bytes]
    trashed = [(s, p) for s, _, p in files if p.rsplit("/", 1)[-1].startswith(".trashed-")]
    apks = [(s, p) for s, _, p in files if p.lower().endswith(APK_EXT)]
    return large, trashed, apks


# --------------------------------------------------------------------------- analysis

def build_tips(r: Report) -> list:
    tips = []
    GB, MB = 1024 ** 3, 1024 ** 2
    if r.volumes:
        v = r.volumes[0]
        pct = v["used"] / v["total"] * 100 if v["total"] else 0
        tips.append(f"Internal storage is {pct:.0f}% full ({fmt(v['free'])} free of {fmt(v['total'])}).")

    total_cache = sum(a.cache for a in r.apps)
    if total_cache > 500 * MB:
        top = ", ".join(f"{a.package} ({fmt(a.cache)})"
                        for a in sorted(r.apps, key=lambda a: a.cache, reverse=True)[:3])
        tips.append(f"App caches total {fmt(total_cache)} (largest: {top}). Clear all app caches safely with:\n"
                    f"      adb shell pm trim-caches 9999G")

    trash = sum(s for s, _ in r.trashed)
    if trash > 50 * MB:
        tips.append(f"{len(r.trashed)} files in the media trash use {fmt(trash)}. "
                    "Empty the trash/'Recently deleted' in your Gallery / Google Photos / Files app.")

    apk = sum(s for s, _ in r.apks)
    if apk > 50 * MB:
        tips.append(f"{len(r.apks)} installer files (.apk) use {fmt(apk)} - they are not needed after installation.")

    wa_backups = sorted((f for f in r.large_files if re.search(r"/WhatsApp[^/]*/Databases/msgstore-", f[2])),
                        key=lambda f: f[1], reverse=True)
    if len(wa_backups) > 1:
        old = wa_backups[1:]
        tips.append(f"{len(old)} older local WhatsApp backups use {fmt(sum(f[0] for f in old))} "
                    f"(newest: {wa_backups[0][2].rsplit('/', 1)[-1]}). WhatsApp only needs the newest one.")

    suspect_paths = {rel for _, rel, _, _ in r.suspects}
    for label, rel, size, hint in r.suspects:
        if size and size > 500 * MB:
            tips.append(f"{label}: {fmt(size)} in /sdcard/{rel}. {hint}")

    # Any app folder in Android/media or Android/data above 1 GB that isn't a known suspect
    for rel, size in sorted(r.folders.items(), key=lambda kv: kv[1], reverse=True):
        if (re.fullmatch(r"Android/(media|data|obb)/[^/]+", rel) and size > GB
                and not any(s.startswith(rel) or rel.startswith(s) for s in suspect_paths)):
            tips.append(f"App folder /sdcard/{rel} holds {fmt(size)} (downloads/offline files of "
                        f"{rel.rsplit('/', 1)[-1]}) - clean up inside that app.")

    big_data = [a for a in r.apps if a.data > 2 * GB]
    for a in big_data[:5]:
        tips.append(f"App {a.package} stores {fmt(a.data)} of data - check its settings for offline content/cache.")

    if r.categories.get("Other", 0) > 5 * GB:
        tips.append(f"'Other' is {fmt(r.categories['Other'])}: this is files outside the standard media folders "
                    "(see the folder list) plus app data not attributed to a package.")
    return tips


def fmt(n: float | None) -> str:
    if n is None:
        return "-"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


# --------------------------------------------------------------------------- terminal output

def bar(value: int, maximum: int, width: int = 24) -> str:
    if maximum <= 0:
        return ""
    n = round(value / maximum * width)
    return "█" * n + "·" * (width - n)


def top_level_folders(r: Report) -> list:
    return sorted(((k, v) for k, v in r.folders.items() if k and "/" not in k),
                  key=lambda kv: kv[1], reverse=True)


def deep_folders(r: Report, n: int) -> list:
    """Folders where the space actually sits: none of their children holds >= 80% of their size."""
    children = {}
    for k, v in r.folders.items():
        if "/" in k:
            parent = k.rsplit("/", 1)[0]
            children[parent] = max(children.get(parent, 0), v)
    items = [(k, v) for k, v in r.folders.items()
             if k.count("/") >= 1 and children.get(k, 0) < 0.8 * v]
    items.sort(key=lambda kv: kv[1], reverse=True)
    return items[:n]


def print_report(r: Report, top: int) -> None:
    H = lambda t: print(f"\n\033[1m=== {t} ===\033[0m")
    d = r.device
    print(f"\n\033[1mStorage report: {d.get('manufacturer','')} {d.get('model','')} "
          f"(Android {d.get('android','?')})\033[0m   scan took {r.scan_seconds:.0f}s")

    H("Volumes")
    for v in r.volumes:
        print(f"  {v['mount']:<24} {bar(v['used'], v['total'])} {fmt(v['used'])} used / {fmt(v['total'])}"
              f"  ({fmt(v['free'])} free)")

    if r.categories:
        H("Categories (Android's own estimate, cached & can be inaccurate - 'System' is often inflated)")
        mx = max(r.categories.values())
        for k, v in sorted(r.categories.items(), key=lambda kv: kv[1], reverse=True):
            print(f"  {k:<16} {bar(v, mx)} {fmt(v):>10}")

    if r.apps:
        H(f"Top {top} apps by size (app + data incl. cache)")
        mx = r.apps[0].total
        w = max(len(a.package) for a in r.apps[:top])
        print(f"  {'package':<{w}} {'':24} {'total':>9} {'app':>9} {'data':>9} {'cache':>9}")
        for a in r.apps[:top]:
            print(f"  {a.package:<{w}} {bar(a.total, mx)} {fmt(a.total):>9} {fmt(a.app):>9} "
                  f"{fmt(a.data):>9} {fmt(a.cache):>9}")
    else:
        H("Apps")
        print("  dumpsys diskstats returned no per-app data on this device.")

    H("Shared storage (/sdcard) – top-level folders")
    tl = top_level_folders(r)
    mx = tl[0][1] if tl else 0
    w = max((len(k) for k, _ in tl[:top]), default=0)
    for k, v in tl[:top]:
        print(f"  {k:<{w}} {bar(v, mx)} {fmt(v):>10}")

    H("Where the space sits (largest folders)")
    df_ = deep_folders(r, top)
    mx = df_[0][1] if df_ else 0
    w = max((len(k) for k, _ in df_), default=0)
    for k, v in df_:
        print(f"  {k:<{w}} {bar(v, mx, 16)} {fmt(v):>10}")

    if r.suspects:
        H("Known storage hogs")
        for label, rel, size, _ in sorted(r.suspects, key=lambda s: s[2] or 0, reverse=True):
            print(f"  {label:<34} {fmt(size):>10}   /sdcard/{rel}")

    H(f"Largest files ({len(r.large_files)} found)")
    for size, mtime, path in r.large_files[:top]:
        date = time.strftime("%Y-%m-%d", time.localtime(mtime)) if mtime else "          "
        print(f"  {fmt(size):>10}  {date}  {path.replace(SDCARD + '/', '/sdcard/')}")

    if r.trashed:
        H(f"Trash (.trashed-*) – {len(r.trashed)} files, {fmt(sum(s for s, _ in r.trashed))}")
        for size, path in r.trashed[:10]:
            print(f"  {fmt(size):>10}  {path.replace(SDCARD + '/', '/sdcard/')}")

    if r.apks:
        H(f"APK installer files – {len(r.apks)} files, {fmt(sum(s for s, _ in r.apks))}")
        for size, path in r.apks[:10]:
            print(f"  {fmt(size):>10}  {path.replace(SDCARD + '/', '/sdcard/')}")

    H("Findings & suggestions")
    for t in r.tips:
        print(f"  • {t}")
    print()


# --------------------------------------------------------------------------- HTML output

def write_html(r: Report, path: str, top: int) -> None:
    e = html.escape

    def rows(items, maxv):
        out = []
        for label, val, extra in items:
            pct = (val / maxv * 100) if maxv else 0
            out.append(f"<tr><td class=l>{e(label)}</td><td class=b><div style='width:{pct:.1f}%'></div></td>"
                       f"<td class=n>{fmt(val)}</td>{extra}</tr>")
        return "\n".join(out)

    sections = []
    for v in r.volumes:
        pct = v["used"] / v["total"] * 100 if v["total"] else 0
        sections.append(f"<div class=vol><b>{e(v['mount'])}</b> – {fmt(v['used'])} of {fmt(v['total'])} used, "
                        f"{fmt(v['free'])} free<div class=meter><div style='width:{pct:.1f}%'></div></div></div>")
    if r.tips:
        sections.append("<h2>Findings &amp; suggestions</h2><ul class=tips>" +
                        "".join(f"<li>{e(t)}</li>" for t in r.tips) + "</ul>")
    if r.categories:
        cats = sorted(r.categories.items(), key=lambda kv: kv[1], reverse=True)
        sections.append("<h2>Categories</h2><table>" +
                        rows([(k, v, "") for k, v in cats], cats[0][1]) + "</table>")
    if r.apps:
        mx = r.apps[0].total
        sections.append("<h2>Apps</h2><table><tr><th>Package</th><th></th><th>Total</th><th>App</th>"
                        "<th>Data</th><th>Cache</th></tr>" +
                        rows([(a.package, a.total, f"<td class=n>{fmt(a.app)}</td><td class=n>{fmt(a.data)}</td>"
                               f"<td class=n>{fmt(a.cache)}</td>") for a in r.apps[:max(top, 50)]], mx) +
                        "</table>")
    tl = top_level_folders(r)
    if tl:
        sections.append("<h2>/sdcard top-level folders</h2><table>" +
                        rows([(k, v, "") for k, v in tl[:top * 2]], tl[0][1]) + "</table>")
    dfold = deep_folders(r, top * 2)
    if dfold:
        sections.append("<h2>Largest sub-folders</h2><table>" +
                        rows([(k, v, "") for k, v in dfold], dfold[0][1]) + "</table>")
    if r.suspects:
        sus = sorted(r.suspects, key=lambda s: s[2] or 0, reverse=True)
        sections.append("<h2>Known storage hogs</h2><table>" +
                        rows([(lbl, s or 0, f"<td class=h>{e(h)}</td>") for lbl, _, s, h in sus],
                             sus[0][2] or 0) + "</table>")
    if r.large_files:
        mx = r.large_files[0][0]
        sections.append(f"<h2>Largest files ({len(r.large_files)})</h2><table>" +
                        rows([(p.replace(SDCARD + "/", "/sdcard/"), s,
                               f"<td class=h>{time.strftime('%Y-%m-%d', time.localtime(m)) if m else ''}</td>")
                              for s, m, p in r.large_files[:200]], mx) + "</table>")
    if r.trashed:
        mx = r.trashed[0][0]
        sections.append(f"<h2>Trash ({len(r.trashed)} files)</h2><table>" +
                        rows([(p.replace(SDCARD + "/", "/sdcard/"), s, "") for s, p in r.trashed[:100]], mx) +
                        "</table>")
    if r.apks:
        mx = r.apks[0][0]
        sections.append(f"<h2>APK files ({len(r.apks)})</h2><table>" +
                        rows([(p.replace(SDCARD + "/", "/sdcard/"), s, "") for s, p in r.apks[:100]], mx) +
                        "</table>")

    d = r.device
    title = f"{d.get('manufacturer', '')} {d.get('model', '')}".strip() or "Android device"
    doc = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Storage Report</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--line:#e7e5e4;--bar:#2563eb;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--bar:#60a5fa;--card:#292524}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,sans-serif;max-width:1000px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0}} .sub{{color:var(--mut);margin-bottom:20px}}
h2{{font-size:16px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}}
table{{width:100%;border-collapse:collapse;table-layout:fixed}} td,th{{padding:3px 6px;text-align:left;font-weight:normal}}
th{{color:var(--mut);font-size:12px}} tr:nth-child(even){{background:var(--card)}}
td.l{{width:42%;overflow-wrap:anywhere}} td.n{{width:10%;text-align:right;font-variant-numeric:tabular-nums}}
td.h{{color:var(--mut);font-size:12px}} td.b div,.meter div{{background:var(--bar);height:10px;border-radius:2px;min-width:1px}}
.meter{{background:var(--line);border-radius:3px;margin-top:6px}} .meter div{{height:14px}} .vol{{margin:8px 0}}
.tips li{{margin:6px 0;white-space:pre-wrap}}
@media (max-width:600px){{td.h{{display:none}} td.l{{width:55%}}}}
</style></head><body>
<h1>Storage report – {e(title)}</h1>
<div class=sub>Android {e(d.get('android', '?'))} · generated {time.strftime('%Y-%m-%d %H:%M')}</div>
{''.join(sections)}
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze storage usage on an Android phone via ADB (read-only).")
    ap.add_argument("-s", "--serial", help="device serial (see 'adb devices')")
    ap.add_argument("--top", type=int, default=20, help="rows per section (default 20)")
    ap.add_argument("--min-file-mb", type=int, default=50, help="report files larger than this (default 50)")
    ap.add_argument("--depth", type=int, default=6, help="folder depth to aggregate (default 6)")
    ap.add_argument("--html", metavar="FILE", help="write an HTML report")
    ap.add_argument("--json", metavar="FILE", help="write raw results as JSON")
    args = ap.parse_args()

    serial = pick_device(args.serial)
    adb = Adb(serial)
    r = Report()
    t0 = time.time()

    def step(msg):
        print(f"\033[2m… {msg}\033[0m", file=sys.stderr, flush=True)

    step("device info");            r.device = collect_device(adb) | {"serial": serial}
    step("volumes");                r.volumes = collect_df(adb)
    step("app sizes (diskstats)");  r.categories, r.apps = collect_diskstats(adb)
    step("listing all files in shared storage")
    files = collect_all_files(adb)
    r.folders = aggregate_folders(files, args.depth)
    r.large_files, r.trashed, r.apks = classify_files(files, args.min_file_mb)
    step("known storage hogs")
    for rel, label, hint in KNOWN_SUSPECTS:
        size = r.folders.get(rel)
        if size:
            r.suspects.append((label, rel, size, hint))
    r.scan_seconds = time.time() - t0
    r.tips = build_tips(r)

    print_report(r, args.top)

    if args.html:
        write_html(r, args.html, args.top)
        print(f"HTML report written to {args.html}")
    if args.json:
        data = asdict(r)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        print(f"JSON written to {args.json}")


if __name__ == "__main__":
    main()

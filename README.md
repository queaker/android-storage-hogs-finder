# android-storage-hogs-finder

Find out what is filling up the storage on an Android phone, via ADB, with
the script `android-storage-hogs-finder.py`.

Android's own storage screen often lumps most of the used space into a vague
"System" or "Other" category. This tool looks at the phone from your computer and
shows you which apps, folders and files actually take up the space, with
concrete suggestions on how to free it.

**Read-only:** the tool only runs `getprop`, `df`, `dumpsys diskstats`, `find` and
`stat` on the phone. It never deletes or changes anything.

## What it reports

- **Volumes:** used and free internal storage
- **Categories:** Android's own estimate (apps, app data, photos, videos, audio, system, …)
- **Apps:** the largest apps by app size, data and cache
- **Shared storage (`/sdcard`):** top-level folders, plus the folders where the space actually sits (the tool drills down past parent folders that just contain one big child)
- **Known storage hogs:** WhatsApp media and local backups, Telegram, Podcast Addict, Pocket Casts, Spotify, YouTube/Netflix downloads, Instagram/TikTok caches, camera and screenshot folders, gallery thumbnails, Downloads, …
- **Largest files:** every file above a size threshold, with its modification date
- **Trash:** media files waiting in the trash (`.trashed-*`, Android 11+)
- **APK files:** leftover installer files
- **Findings & suggestions:** for example "2 older local WhatsApp backups use 1.3 GB", the total size of app caches, or app folders above 1 GB

The report appears in the terminal. With the options below, it is also written as a self-contained HTML page (light/dark mode) and/or as raw JSON.

## Requirements

- macOS, Linux or Windows with **Python 3.9+**. Only the standard library is used, so there is nothing to `pip install`.
- **ADB** (Android platform tools):
  - macOS: `brew install android-platform-tools`
  - Debian/Ubuntu: `sudo apt install adb`
  - Windows: [SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)
- An Android phone with **USB debugging** enabled:
  1. *Settings → About phone →* tap **Build number** 7 times to unlock the developer options
  2. *Settings → System → Developer options →* turn on **USB debugging**
  3. Connect the phone by USB, unlock it and accept the **"Allow USB debugging?"** prompt
  4. Check the connection: `adb devices` should list the phone as `device`

You don't need root.

## Usage

```bash
python3 android-storage-hogs-finder.py                        # terminal report
python3 android-storage-hogs-finder.py --html report.html     # also write an HTML report
python3 android-storage-hogs-finder.py --json report.json     # also dump the raw data as JSON
python3 android-storage-hogs-finder.py -s <serial>            # pick a device when several are connected
python3 android-storage-hogs-finder.py --min-file-mb 100 --top 30
```

| Option | Default | Meaning |
|---|---|---|
| `-s`, `--serial` | – | Device serial from `adb devices` (only needed when several are connected) |
| `--top N` | 20 | Rows shown per section |
| `--min-file-mb N` | 50 | List files larger than N MB |
| `--depth N` | 6 | How many folder levels to add up |
| `--html FILE` | – | Write an HTML report |
| `--json FILE` | – | Write the raw results as JSON |

A scan usually takes 10–30 seconds, depending on how many files the phone has.

> **Privacy:** the reports contain app names and the paths of your files.
> Keep them local and don't share them.

## Demo run

A real run on a Google Pixel 7 (Android 17). The diskstats categories and app
sizes are Android's cached estimate; the folder and file numbers come from the
live scan. App, folder and file names have been replaced with demo names
(`com.example.*`, `Podcast A`, `episode-01.mp3`, …); the sizes are real.

```text
$ python3 android-storage-hogs-finder.py --top 15 --html storage_report.html --json storage_report.json
… device info
… volumes
… app sizes (diskstats)
… listing all files in shared storage
… known storage hogs

Storage report: Google Pixel 7 (Android 17)   scan took 37s

=== Volumes ===
  /data/user/0             █████████████████████··· 95.2 GB used / 109.9 GB  (14.6 GB free)

=== Categories (Android's own estimate, cached & can be inaccurate - 'System' is often inflated) ===
  System           ████████████████████████   119.2 GB
  Audio            ████████················    37.4 GB
  App              ██████··················    30.5 GB
  App Data         █████···················    24.0 GB
  Photos           █·······················     6.4 GB
  Other            █·······················     4.4 GB
  Videos           ························     1.7 GB
  App Cache        ························   704.7 MB
  Downloads        ························        0 B

=== Top 15 apps by size (app + data incl. cache) ===
  package                                             total       app      data     cache
  com.example.chat       ████████████████████████    2.5 GB  142.4 MB    2.4 GB    892 KB
  com.example.messenger  ███████████████████████·    2.5 GB  199.1 MB    2.3 GB   18.2 MB
  com.example.services   ██████████████··········    1.5 GB  268.1 MB    1.2 GB    1.7 MB
  com.example.kids       ██████████████··········    1.5 GB    1.3 GB  139.2 MB      4 KB
  com.example.search     ██████████████··········    1.5 GB  490.4 MB 1004.4 MB  234.4 MB
  com.example.tts        ████████████············    1.3 GB  101.9 MB    1.2 GB       0 B
  com.example.neighbors  ████████████············    1.2 GB   97.0 MB    1.1 GB     92 KB
  com.example.music      ██████████··············    1.1 GB  175.5 MB  942.6 MB    156 KB
  com.example.video      ██████████··············    1.1 GB  194.9 MB  897.9 MB  116.2 MB
  com.example.assistant  ██████████··············    1.1 GB  171.4 MB  906.9 MB       0 B
  com.example.mail       █████████··············· 1001.9 MB  234.7 MB  767.2 MB    1.4 MB
  com.example.social     █████████···············  960.9 MB  554.4 MB  406.5 MB    7.0 MB
  com.example.photoshare ████████················  920.1 MB  590.7 MB  329.3 MB   38.8 MB
  com.example.browser    ███████·················  777.1 MB  257.7 MB  519.5 MB   22.5 MB
  com.example.smarthome  ███████·················  728.9 MB  353.6 MB  375.4 MB      4 KB

=== Shared storage (/sdcard) – top-level folders ===
  Android       ████████████████████████    35.6 GB
  DCIM          ························   621.8 MB
  Pictures      ························    93.0 MB
  Movies        ························    90.9 MB
  CameraSync    ························    41.4 MB
  Download      ························    35.4 MB
  Documents     ························     7.9 MB
  .downloader   ························     2.8 MB
  Video         ························     1.6 MB
  Recordings    ························     439 KB
  Music         ························      20 KB
  Notifications ························      13 KB

=== Where the space sits (largest folders) ===
  Android/media/com.example.podcasts/podcast                           ████████████████    27.7 GB
  Android/media/com.example.podcasts/podcast/Podcast A                 ████████········    13.2 GB
  Android/media/com.example.podcasts/podcast/Podcast B                 ███████·········    11.4 GB
  Android/media/com.example.messenger/Messenger                        ████············     6.3 GB
  Android/media/com.example.messenger/Messenger/Media                  ██··············     4.0 GB
  Android/media/com.example.messenger/Messenger/Media/Messenger Images ██··············     3.2 GB
  Android/media/com.example.messenger/Messenger/Databases              █···············     2.3 GB
  Android/media/com.example.podcasts/podcast/thumbnails                █···············     2.0 GB
  Android/data                                                         █···············     1.4 GB
  DCIM/Camera                                                          ················   621.8 MB
  Android/media/com.example.messenger/Messenger/Media/Messenger Video  ················   531.4 MB
  Android/data/com.example.music/files/cache                           ················   475.5 MB
  Android/media/com.example.podcasts/podcast/Podcast C                 ················   331.4 MB
  Android/media/com.example.podcasts/podcast/Podcast D                 ················   323.1 MB
  Android/data/com.example.music/files/cache/Users                     ················   309.6 MB

=== Known storage hogs ===
  Podcast app episodes                  27.8 GB   /sdcard/Android/media/com.example.podcasts
  Messenger media                        4.0 GB   /sdcard/Android/media/com.example.messenger/Messenger/Media
  Messenger backups (local)              2.3 GB   /sdcard/Android/media/com.example.messenger/Messenger/Databases
  Camera photos & videos               621.8 MB   /sdcard/DCIM/Camera
  Music app offline files              475.5 MB   /sdcard/Android/data/com.example.music
  Movies folder                         90.9 MB   /sdcard/Movies
  Screenshots                           53.7 MB   /sdcard/Pictures/Screenshots
  Downloads folder                      35.4 MB   /sdcard/Download
  Messenger 2 cache                     28.2 MB   /sdcard/Android/data/com.example.messenger2
  Gallery thumbnails (Pictures)         10.3 MB   /sdcard/Pictures/.thumbnails
  Recordings                             439 KB   /sdcard/Recordings
  Video app downloads                     123 B   /sdcard/Android/data/com.example.video
  Streaming app downloads                  20 B   /sdcard/Android/data/com.example.streaming

=== Largest files (247 found) ===
    966.7 MB  2026-10-22  /sdcard/Android/media/com.example.messenger/Messenger/Databases/backup-YYYY-MM-03.1.db.crypt14
    688.2 MB  2026-10-21  /sdcard/Android/media/com.example.messenger/Messenger/Databases/backup-YYYY-MM-02.1.db.crypt14
    687.8 MB  2026-10-20  /sdcard/Android/media/com.example.messenger/Messenger/Databases/backup-YYYY-MM-01.1.db.crypt14
    355.9 MB  2026-11-03  /sdcard/DCIM/Camera/VID_0001.mp4
    175.7 MB  2025-12-16  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-01.mp3
    163.0 MB  2026-09-01  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-02.mp3
    162.9 MB  2026-03-17  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-03.mp3
    162.5 MB  2026-05-07  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-04.mp3
    160.9 MB  2026-10-06  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-05.mp3
    160.6 MB  2025-08-01  /sdcard/Android/media/com.example.podcasts/podcast/Podcast B/episode-01.mp3
    160.4 MB  2026-04-21  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-06.mp3
    159.9 MB  2024-11-19  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-07.mp3
    159.2 MB  2026-05-12  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-08.mp3
    159.0 MB  2026-07-28  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-09.mp3
    158.6 MB  2024-10-15  /sdcard/Android/media/com.example.podcasts/podcast/Podcast A/episode-10.mp3

=== Findings & suggestions ===
  • Internal storage is 87% full (14.6 GB free of 109.9 GB).
  • App caches total 704.7 MB (largest: com.example.search (234.4 MB), com.example.video (116.2 MB), com.example.browser2 (85.5 MB)). Clear all app caches safely with:
      adb shell pm trim-caches 9999G
  • 2 older local Messenger backups use 1.3 GB (newest: backup-YYYY-MM-03.1.db.crypt14). Messenger only needs the newest one.
  • Messenger media: 4.0 GB in /sdcard/Android/media/com.example.messenger/Messenger/Media. Messenger > Settings > Storage > Manage storage. Disable auto-download for groups.
  • Messenger backups (local): 2.3 GB in /sdcard/Android/media/com.example.messenger/Messenger/Databases. Old local backup-*.db.crypt backups can be deleted; keep the newest.
  • Podcast app episodes: 27.8 GB in /sdcard/Android/media/com.example.podcasts. Podcast app > Settings > Automatic cleanup: delete played episodes, limit episodes kept per podcast.
  • Camera photos & videos: 621.8 MB in /sdcard/DCIM/Camera. Back up (e.g. to a cloud photo service) and use 'Free up space'.
  • App com.example.chat stores 2.4 GB of data - check its settings for offline content/cache.
  • App com.example.messenger stores 2.3 GB of data - check its settings for offline content/cache.

HTML report written to storage_report.html
JSON written to storage_report.json
```

## Freeing space

The tool only suggests what to clean up. Typical next steps:

| Finding | Action |
|---|---|
| Podcast episodes | In the podcast app, turn on automatic deletion of played episodes and limit the episodes kept per podcast |
| WhatsApp media | *WhatsApp → Settings → Storage and data → Manage storage*; turn off auto-download for groups |
| Old WhatsApp backups | Delete the old `msgstore-YYYY-MM-DD.*.db.crypt*` files; keep the newest |
| App caches | `adb shell pm trim-caches 9999G` clears the caches of all apps (safe; apps rebuild them as needed) |
| Trash (`.trashed-*`) | Empty "Recently deleted" in Google Photos, the gallery app or Files |
| Camera | Back up your photos and videos, then use *Google Photos → Free up space* |
| APK files | Delete them; installed apps don't need them |

## How it works

| Data | Source |
|---|---|
| Device info | `getprop` |
| Free/used space | `df -k /data /storage/emulated/0` |
| Categories & per-app sizes | `dumpsys diskstats` (cached by Android, may be up to a day old) |
| Files & folders | `find /storage/emulated/0/ -type f -print0 \| xargs -0 -n 200 stat -c '%s\|%Y\|%n'` (one pass; folder sizes are added up in Python) |

### Why not `du`?

Two quirks of the toybox tools that ship with Android turned up on a real device (Pixel 7):

- `du` prints **nothing at all** for a directory tree if one subfolder inside it is unreadable (e.g. `Permission denied` inside another app's `Android/data` folder). Because of this, a 40 GB folder was missing from the results.
- `find … -exec stat {} +` silently drops whole batches of files with `Argument list too long` when the paths are long.

The tool therefore lists every file once, with small `xargs` batches, and adds up the folder sizes itself.

## Limitations

- **App-private data** (`/data/data/<package>`) can't be read without root. For it, the tool relies on the per-app numbers from `dumpsys diskstats`.
- The **diskstats categories** are Android's own estimate and are refreshed only about once a day. "System" is often inflated and can even exceed the total storage size. The file scan of `/sdcard` is the precise number.
- **Android/data** folders of some apps are unreadable even for ADB. These files are skipped and not counted.
- **App names:** the tool shows package names (e.g. `com.google.android.calculator` = Calculator), not the names shown in the launcher.

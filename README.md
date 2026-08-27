# Photosplit

Put several photos on the flatbed, press one button, get one cropped,
straightened file per photo. No other steps.

Photosplit drives the scanner through macOS's own ImageCaptureCore framework —
the same plumbing Image Capture.app uses — so any scanner that already works on
your Mac works here, with no extra driver. It scans the whole bed, finds each
print, rotates out the skew from laying them down by hand, crops to the print's
edge, and saves them into the folder you picked.

## Install

Any Mac, Apple Silicon or Intel, macOS 11 or newer.

```bash
git clone <this repo> ~/Documents/GitHub/photosplit
cd ~/Documents/GitHub/photosplit && ./install.sh
```

That builds a self-contained virtualenv, `Photosplit.app`, and a `photosplit`
command in `~/.local/bin`. Drag `Photosplit.app` to your Dock. Re-run
`./install.sh` any time; it is idempotent.

The path above is only a convention — clone it wherever you keep repositories.
But **if you move the repo afterwards, re-run `./install.sh`**. The virtualenv,
the `~/.local/bin` symlink and the app bundle all bake in absolute paths, and
they break silently until the script rewrites them.

To set up a second Mac, clone the repo there and run `./install.sh` again. The
virtualenv is built per machine, so do not copy `.venv` between them.

## Use

Open Photosplit, put the photos on the glass, close the lid, press **Scan**.
The window shows what it found and where it went; the folder opens when it is
done. Then load the next batch and press Scan again.

Everything adjustable is in **Preferences** (⌘,):

| Setting | Default |
| --- | --- |
| Save photos to | `~/Pictures/Photosplit` |
| Resolution | 600 dpi — good for prints you may enlarge or analyse; 300 is fine for quick copies, 1200 is slow and rarely worth it |
| Save as | JPEG, PNG (lossless), or TIFF (lossless) |
| JPEG quality | 95. Measured at ~49 dB PSNR against the uncompressed crop, so it is visually transparent; 100 costs about 2.4x the file size for ~3 dB. For analysis work choose PNG or TIFF instead and skip the question |
| Scan in colour | on |
| Ignore anything smaller than | 1 inch — raises this to reject dust |
| Straighten crooked photos | on |
| Trim leftover scanner background | on |
| Keep the full scan as well | off |
| Save a marked-up preview of each scan | off — turn on to see what it detected |
| Open the folder when a scan finishes | on |

**Calibrate…** in Preferences scans the empty bed and records what is on it.
Run it when a scanner is new to you and after every time you clean the glass.
It reports how many specks it found, whether that is better or worse than the
last calibration, and how far in from the edge the bed is too dark to lay a
print — and it saves `dust-map.json` and `dust-map.png` to
`~/Library/Application Support/Photosplit`.

Calibration always scans at 600 dpi whatever the Resolution setting says, so
one calibration can be compared against the next.

Compressed air is a poor way to clean a flatbed: it lifts dust out of the
housing and onto the glass. A microfibre cloth measurably works. The
calibration will tell you which you did.

Files are named by the moment they were scanned, so nothing ever overwrites
anything: `2026-08-26-143205-01.jpg`, `-02`, and so on.

You can also drop scans you already have onto the app icon, and they are split
with the same settings. Your originals are left alone.

## Quality

Crops are cut from the scan without resampling whenever a print is square to
the glass, and with a single interpolation pass when it needs straightening.
Nothing is downscaled, and the scan's real resolution is written into every
file. Doubling the resolution quadruples both the scan time and the file size,
so 600 dpi is the default rather than 1200.

## Scanning tips

- Leave a **visible gap** between prints, about a quarter inch. Touching prints
  are handled, but a gap makes it certain.
- Prints do not need to be square to the glass; skew up to 45° is corrected.
- Close the lid. The white backing is what tells Photosplit where a photo stops.
- **The scannable area is usually smaller than the glass.** Most flatbeds stop
  at Letter or A4 even though the plate extends past the markers, so a print
  sitting on glass beyond them is simply out of reach — of any software. Keep
  prints inside the markers, and scan fewer per pass rather than packing the
  bed. Photosplit says so in its log when a photo reaches the edge.

To see exactly what your scanner can reach:

```bash
.venv/bin/python tools/scanner_info.py
```

## The command line

The same engine, for scans you already have on disk:

```bash
photosplit ~/Pictures/Scans -o ~/Pictures/Photos --preview
```

`--dry-run` reports without writing. `photosplit --help` lists the rest.

## When it gets something wrong

Turn on the marked-up preview first — it shows exactly what was detected.

| Symptom | Preference | Command line |
| --- | --- | --- |
| One photo came out as several pieces | — | `--min-fill 0.4` |
| Two photos merged into one crop | — | `--separation 0.06` |
| Small prints ignored | Ignore anything smaller than: 0.5" | `--min-size 0.6` |
| Dust picked up as photos | Ignore anything smaller than: 1.5" | `--min-size 1.5` |
| A white border got shaved off | Trim leftover background: off | `--no-trim` |
| Crops look slightly rotated | Straighten: off | `--no-deskew` |
| Everything has a colour tint | — | `--neutralise` |

## Colour

`--neutralise` colour-balances a scan against its own lid. The lid is white, so
whatever tint it comes back with is the scanner's, or the mat's, and the same
tint lies over the prints; dividing it out takes it off the photographs too.
On the Epson V500 this takes the lid from R 237.4, G 241.8, B 244.4 — four
levels of blue over everything — down to neutral, leaving sharpness, shadow
detail and highlights where they were.

It fixes neutrality, not colour accuracy: it makes a known white read as white,
but cannot tell you whether a red is the right red. That needs a target with
known values on the glass, an IT8 or a ColorChecker. It is off by default,
because it changes the colour of what you get out.

## Comparing two scanners

`tools/scan_quality.py` measures a full-bed scan so the same photos can be run
through two scanners and the results diffed:

```bash
.venv/bin/python tools/scan_quality.py "~/Pictures/Photosplit/Full Scans/"*.tiff
```

`tools/scan_blank.py` measures the other half: the bed itself, scanned with the
lid closed and nothing on the glass. It finds dirt, tells you whether it is on
the glass or inside the optics, measures how far each edge darkens before the
lighting evens out, and reports whether the colour cast is the same across the
bed. Run it when a scanner is new to you, and after cleaning the glass to see
whether the cleaning helped.

```bash
.venv/bin/python tools/scan_blank.py blank.tiff --map dust.png
```

It reports colour neutrality, noise, edge sharpness, and how much tonal range
survives — all measured off the prints and the lid, so the numbers do not
depend on what the photographs contain. It cannot measure absolute colour
accuracy; that needs a reference target (IT8 or ColorChecker) on the glass.
Baselines live in `quality/`.

## Layout

| File | What it does |
| --- | --- |
| `photosplit/scanner.py` | Drives the scanner through ImageCaptureCore |
| `photosplit/detect.py` | Separates photo from scanner lid, one rectangle per print |
| `photosplit/extract.py` | Rotates, crops, trims, saves; draws the preview |
| `photosplit/split.py` | The scan-to-files step, shared by the app and the CLI |
| `photosplit/app.py` | The window, the Scan button, Preferences |
| `photosplit/prefs.py` | Settings, stored in NSUserDefaults |
| `photosplit/cli.py` | The `photosplit` command |
| `build_app.sh` | Assembles `Photosplit.app` |
| `tools/scan_quality.py` | Measures a scan, for comparing scanners |
| `tools/scanner_info.py` | Reports a scanner's reachable area and resolutions |

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Detection is checked against synthetic scans with known photo placements, and
the app's windows are built offscreen and inspected — including a contrast check
that fails if the log is ever unreadable in dark mode.

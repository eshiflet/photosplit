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
git clone <this repo> ~/photosplit && cd ~/photosplit && ./install.sh
```

That builds a self-contained virtualenv, `Photosplit.app`, and a `photosplit`
command in `~/.local/bin`. Drag `Photosplit.app` to your Dock. Re-run
`./install.sh` any time; it is idempotent.

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
| Resolution | 300 dpi (use 600 for wallet-size or anything you may enlarge) |
| Save as | JPEG, PNG, or TIFF |
| Scan in colour | on |
| Ignore anything smaller than | 1 inch — raises this to reject dust |
| Straighten crooked photos | on |
| Trim leftover scanner background | on |
| Keep the full scan as well | off |
| Save a marked-up preview of each scan | off — turn on to see what it detected |
| Open the folder when a scan finishes | on |

Files are named by the moment they were scanned, so nothing ever overwrites
anything: `2026-08-26-143205-01.jpg`, `-02`, and so on.

You can also drop scans you already have onto the app icon, and they are split
with the same settings. Your originals are left alone.

## Scanning tips

- Leave a **visible gap** between prints, about a quarter inch. Touching prints
  are handled, but a gap makes it certain.
- Prints do not need to be square to the glass; skew up to 45° is corrected.
- Close the lid. The white backing is what tells Photosplit where a photo stops.

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

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Detection is checked against synthetic scans with known photo placements, and
the app's windows are built offscreen and inspected — including a contrast check
that fails if the log is ever unreadable in dark mode.

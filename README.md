# photosplit

Scan several photos at once on a flatbed, get one cropped, straightened image
file per photo. That is the whole program — the one job you would otherwise buy
VueScan for.

It reads a scan you have already made (Image Capture, Preview, or whatever came
with the scanner), finds each print on the glass, rotates out the few degrees of
skew from laying them down by hand, crops to the print's edge, and writes
`scan-01.jpg`, `scan-02.jpg`, and so on at the scan's original resolution.

## Install

Works on any Apple Silicon or Intel Mac with Python 3.9 or newer.

```bash
git clone <this repo> ~/photosplit && cd ~/photosplit && ./install.sh
```

That builds a self-contained virtualenv, puts a `photosplit` command in
`~/.local/bin`, and builds `Photosplit.app`, a drag-and-drop droplet. Re-run it
any time; it is idempotent. To set up the second Mac, copy or clone the folder
there and run `./install.sh` again — the virtualenv is per-machine, so do not
copy `.venv` across.

## Use

Drag a scan (or a folder of scans) onto `Photosplit.app`, or:

```bash
photosplit ~/Pictures/scan-001.tif
```

Crops land in a `split` folder beside the scan. Point a whole shoebox at it:

```bash
photosplit ~/Pictures/Scans -o ~/Pictures/Photos --preview
```

`--preview` also writes a copy of the scan with a red box and a number around
every photo it found, which is the fastest way to see what it did.

Check before writing anything:

```bash
photosplit ~/Pictures/Scans --dry-run
```

## Scanning tips

- Leave a **visible gap** between prints, about a quarter inch. Touching prints
  are handled, but a gap makes it certain.
- Prints do not need to be square to the glass; skew up to 45° is corrected.
- Scan at **300 dpi** for 4x6s, **600 dpi** for wallet-size or anything you may
  want to enlarge. The crops keep whatever resolution the scan had, and the dpi
  is written into each file.
- Close the lid. The white backing is what tells the program where a photo stops.

## When it gets something wrong

| Symptom | Fix |
| --- | --- |
| One photo came out as several pieces | `--min-fill 0.4` |
| Two photos merged into one crop | `--separation 0.06` |
| Small prints ignored | `--min-size 0.6` |
| Dust or lint picked up as photos | `--min-size 1.5` |
| A white border got shaved off | `--no-trim` |
| Crops look slightly rotated | `--no-deskew` |
| Sizes reported wrong | `--dpi 600` (scan had no resolution tag) |

`photosplit --help` lists everything.

## Layout

| File | What it does |
| --- | --- |
| `photosplit/detect.py` | Separates photo from scanner lid, returns a rectangle per print |
| `photosplit/extract.py` | Rotates, crops, trims, and saves; draws the preview |
| `photosplit/cli.py` | Argument handling and the batch loop |
| `tests/make_scan.py` | Builds synthetic scans with known photo placements |
| `tests/test_photosplit.py` | Checks detection against those known placements |

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

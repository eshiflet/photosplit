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
git clone <this repo> photosplit
cd photosplit && ./install.sh
```

That builds a self-contained virtualenv, `Photosplit.app`, and a `photosplit`
command in `~/.local/bin`. Drag `Photosplit.app` to your Dock. Re-run
`./install.sh` any time; it is idempotent.

Clone it wherever you keep repositories. But **if you move it afterwards,
re-run `./install.sh`**. The virtualenv, the `~/.local/bin` symlink and the app
bundle all bake in absolute paths, and they break silently until the script
rewrites them.

To set up a second Mac, clone the repo there and run `./install.sh` again. The
virtualenv is built per machine, so do not copy `.venv` between them.

## Use

Open Photosplit, choose what you are scanning — **Prints**, **Film** or
**Slides** — put them on the glass, close the lid, and press the button, which
names what it is about to do: **Run Print Scan**, **Run Film Scan**, **Run
Slide Scan**. The window shows what it found and where it went; the folder
opens when it is done. Then load the next batch and press it again.

Each mode keeps its own settings, because what is right for a print is wrong
for a 35 mm frame.

Everything adjustable is in **Preferences** (⌘,), on two pages. **Scanning**
is how the scan is made; **Post-Processing** is what is done to it afterwards,
on the saved file rather than by the scanner. Both are per mode.

| Setting | Default |
| --- | --- |
| Save photos to | `~/Pictures/Photosplit` |
| Resolution | Per mode. 600 dpi for prints; 2400 for film, where the frame is 35 mm wide and needs it |
| Scanning | Prints, Film, or Slides. Film and slides both go through the positive transparency unit — the one that hands back what is actually on the film — but they are separate modes because they use different holders: a strip is one ribbon of frames, slides are individual mounts sitting apart. Inverting a negative is done afterwards, on the scan, so it can be redone without scanning again |
| Save as | PNG (lossless) by default; JPEG or TIFF if you prefer |
| Depth | 16-bit, which matters most for negatives: inverting one stretches a narrow slice of the range across the whole output, and 8-bit does not have the levels to survive it |
| JPEG quality | 95. Measured at ~49 dB PSNR against the uncompressed crop, so it is visually transparent; 100 costs about 2.4x the file size for ~3 dB. For analysis work choose PNG or TIFF instead and skip the question |
| Scan in colour | on |
| Ignore anything smaller than | 1 inch for prints, 0.5 for film — a 35 mm frame is 0.94 in on its short side, so the print threshold would discard every one |
| Negatives — turn them into positives | Post-Processing. On for film, off for prints and slides |
| Remove dust specks | Post-Processing. Off by default, and unavailable below 1200 dpi — under that a speck cannot be told from film grain, and what it finds in a lawn is the clover |
| Ring them instead of removing them | Post-Processing. Writes the crops with every speck circled instead of filled, so you can see what would go before it goes |
| Also heal the dirt the last calibration found | Post-Processing. Needs a calibration, not a resolution: the position is known rather than detected, so it works at any dpi and cannot mistake the photograph for dirt |
| Metadata | Post-Processing. Free text — film, exposure, what the picture is of — written into every PNG as a Description, where any image tool will find it |
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

Pressing **Run Calibration** closes Preferences and returns you to the main
window, where the log shows the scan going and the verdict when it lands.

Calibration always scans at 600 dpi whatever the Resolution setting says, so
one calibration can be compared against the next. The last five runs are kept,
newest first, so a glass that is slowly getting worse shows up as a trend
rather than a single number:

```
Glass calibrated: 52 speck(s), 0.0015% of the bed, largest 0.72 mm.
  cleaner than last time (98 speck(s))
  last 4 runs, newest first: 52, 98, 51, 71
  Keep prints 0.35 in clear of the left edge: the bed is dark there and photos in it merge.
```

Compressed air is a poor way to clean a flatbed: it lifts dust out of the
housing and onto the glass. A microfibre cloth measurably works. The
calibration will tell you which you did.

Files are named by the moment they were scanned, so nothing ever overwrites
anything: `2026-08-26-143205-01.png`, `-02`, and so on.

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
| A slide keeps a black rim from its mount | Trim leftover background: on | (on by default) |
| Crops look slightly rotated | Straighten: off | `--no-deskew` |
| Everything has a colour tint | — | `--neutralise` |
| A strip of film came out as one image | Scanning: Film | `--film` |

## Film and slides

Both go through the scanner's transparency unit, and both need its film holder;
most flatbeds also need the white document mat taken out of the lid, because it
covers the lamp that shines through the film. **If a film scan never starts,
that mat is the first thing to check** — the scanner usually reports no error,
it simply waits. Photosplit says so in its log if nothing arrives.

Slides need nothing special beyond that: they are separate mounts with holder
between them, which is the same problem as prints on a lid, and the ordinary
detector handles it.

A strip is different. A strip is not a set of separate photographs. The frames touch, parted only by
a rebate line a couple of millimetres wide, so the detector that finds prints
on a lid sees one long ribbon. `--film`, and the Film mode in the app, uses a
different one.

It splits the strip at its rebate lines, found by brightness rather than by
texture: unexposed film base is the thinnest part of a negative, so scanned
through the positive unit it is the brightest thing on the film, and it reads
the same at every gap. Texture would seem the obvious signal and is the wrong
one — a frame of empty sky is flatter than the gaps either side of it. A slot
with no film in it is brighter still and is skipped.

### Turning a negative into a positive

Film mode inverts by default; the checkbox in Preferences turns it off for
slide film that came in an uncut strip. `--invert` does the same on the
command line.

The orange mask is not divided out by a constant. Every stock has its own, age
shifts it, and processing shifts it again, so it is **measured from the strip
being scanned** — off the unexposed rebate between the frames, the same way
`--neutralise` measures a lid. A roll developed badly thirty years ago
calibrates itself.

What gets inverted is density rather than brightness. Film records the
logarithm of exposure, so each pixel's distance from the base in log space is
what the scene did, and a display gamma at the end turns that back into
something to look at.

Colour on old film is approximate and always will be. The scan kept on disk is
the raw one, so a better inversion later costs a re-run rather than a re-scan.

### Dust

Off by default, and only offered at 1200 dpi or better. Below that the smallest
speck worth removing covers fewer pixels than the grain does, and the two are
not separable — on a 600 dpi frame of a lawn what it finds is the clover.

A speck has to be small in real units, roughly blob shaped, sitting in a smooth
surround, and standing well clear of it. A plain threshold instead finds every
sharp highlight in the picture. Nothing on a busy background is touched, which
is also where a speck would not have shown anyway.

Dirt **on the glass** is a separate and easier case, and the calibration
already knows where it is: `--glass-dust`, or the checkbox in the app, heals
those positions directly. Nothing is detected, so nothing in the photograph can
be mistaken for dirt, and it works at any resolution. It covers only the platen
— dust on the film itself still needs detecting — and it is ignored if the
calibration is more than a month old, because after a clean the map is a list
of places with nothing in them.

**Look before removing.** `--dust-preview`, and the checkbox beside it in the
app, writes the crops with every speck ringed rather than filled. Removing one
is not reversible in the file that gets written, and a false positive takes
part of the photograph with it.

Infrared cleaning would be better than any of this and is not available:
ImageCaptureCore has no infrared pixel type, and on silver-based black-and-white
film the image itself is opaque to infrared, so even a scanner offering it would
read the whole frame as one defect.

## Colour

`--neutralise` colour-balances a scan against its own lid. The lid is white, so
whatever tint it comes back with is the scanner's, or the mat's, and the same
tint lies over the prints; dividing it out takes it off the photographs too.
On a scanner whose lid reads a few levels blue, this takes it to neutral and
leaves sharpness, shadow detail and highlights where they were.

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

`quality/` holds measurements taken with these tools, and `quality/README.md`
explains which figures may be compared between scanners and which may not —
including one, edge rise, that looks like a measure of sharpness and is not.

## Layout

| File | What it does |
| --- | --- |
| `photosplit/scanner.py` | Drives the scanner through ImageCaptureCore |
| `photosplit/detect.py` | Separates photo from scanner lid, one rectangle per print |
| `photosplit/film.py` | Splits a strip of film into frames at its rebate lines |
| `photosplit/negative.py` | Turns a scanned negative into a positive |
| `photosplit/blank.py` | Measures an empty bed: dirt, vignetting, colour cast |
| `photosplit/extract.py` | Rotates, crops, trims, saves; draws the preview |
| `photosplit/split.py` | The scan-to-files step, shared by the app and the CLI |
| `photosplit/app.py` | The window, the scan button, Preferences, calibration |
| `photosplit/prefs.py` | Settings, stored in NSUserDefaults |
| `photosplit/cli.py` | The `photosplit` command |
| `build_app.sh` | Assembles `Photosplit.app` |
| `tools/scan_quality.py` | Measures a scan, for comparing scanners |
| `tools/scanner_info.py` | Reports a scanner's reachable area and resolutions |
| `tools/scan_blank.py` | Measures an empty bed from the command line |

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Detection is checked against synthetic scans with known photo placements, and
the app's windows are built offscreen and inspected — including a contrast check
that fails if the log is ever unreadable in dark mode.

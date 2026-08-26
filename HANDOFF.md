# Handoff

Everything a fresh session needs to pick this up, on this machine or another.
The conversation that produced it does not travel; this file and the commit
history are the record.

## What this is

Photosplit scans a flatbed full of photographs and saves each one as its own
cropped, straightened file. One button. It drives the scanner through macOS's
ImageCaptureCore, so any scanner that works in Image Capture works here.

Read `README.md` first for how to use it, then `git log` — the commit messages
carry the reasoning behind every non-obvious decision, including the ones that
were wrong first.

## Where things stand

Working and verified against a real scanner (an HP Color LaserJet Pro M478f,
over the network):

- Scan, split, save, end to end, at 300, 600 and 1200 dpi.
- 42 tests pass. `build_app.sh` also builds the interface inside the finished
  bundle and fails if it cannot start there.
- Baselines for scanner comparison are in `quality/`, with `quality/README.md`
  explaining which figures may be compared and which may not.

## What is next

Run the **same five prints, same positions** on the Epson Perfection V500
attached to the Mac Mini, twice — once at 600 dpi and once at 1200 — both saved
as PNG. Then:

```bash
.venv/bin/python tools/scan_quality.py "path/to/epson-600.tiff" \
    --json quality/epson-v500-600dpi.json
```

and compare against `quality/hp-m478f-*.json`.

The question being answered is whether the HP or the Epson makes better scans.
What is already known about the HP:

- Lid neutrality is good (colour cast 0.30 at 600 dpi) and noise is low (1.07).
- **It crushes shadows: 4-5% of pixels at pure black, 1st percentile 0.0, at
  every resolution tested.** This is its clearest weakness and the first thing
  to check on a dedicated photo scanner.
- Its 1200 dpi is optically real, not interpolated, and its optical edge spread
  is about 150 um.

## Traps worth knowing

- **Compare optics only at each scanner's highest resolution.** Below that the
  edge-rise figure is pinned at ~2 pixels and reports the resolution chosen
  rather than the lens. This produced a wrong conclusion once already.
- **Tonal figures only compare across scans holding the same prints.** Shadow,
  highlight, clipping and saturation describe the photographs, not the scanner.
- **The scannable area is smaller than the glass** — A4 on the HP, even though
  the plate extends past the markers. Photosplit flags photos that reach the
  boundary; heed it. Check any new scanner with `tools/scanner_info.py`.
- **1200 dpi peaks at ~2.9 GB of memory** during the split. Check the machine
  can afford it before making it routine.
- Photosplit straightens photos but cannot know which way is up. A print laid
  sideways is saved sideways.
- Tests must never touch the installed app's preferences. `Prefs` takes a suite
  name and the tests point it at a throwaway domain; keep it that way.

## Setting up on another Mac

```bash
git clone <this repo> ~/photosplit && cd ~/photosplit && ./install.sh
```

The virtualenv is built per machine — never copy `.venv` between them. Both an
Apple Silicon and an Intel Mac work; macOS 11 or newer.

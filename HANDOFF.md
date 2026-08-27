# Handoff

Everything a fresh session needs to pick this up, on this machine or another.
The conversation that produced it does not travel; this file and the commit
history are the record.

## What this is

Photosplit scans a flatbed and saves each photograph on it as its own cropped,
straightened file. It handles prints on the glass, strips of film, and mounted
slides, and it drives the scanner through macOS's ImageCaptureCore, so any
scanner that works in Image Capture works here.

Read `README.md` first for how to use it, then `git log` — the commit messages
carry the reasoning behind every non-obvious decision, including the ones that
were wrong first.

## Where things stand

All three media work end to end against real hardware. 103 tests pass, and
`build_app.sh` builds the interface inside the finished bundle and fails if it
cannot start there.

| Mode | Unit | Default | Detector |
| --- | --- | --- | --- |
| Prints | flatbed | 600 dpi, 16-bit, PNG | `detect.find_photos` |
| Film | positive transparency | 2400 dpi, 16-bit, PNG, inverted | `film.find_frames` |
| Slides | positive transparency | 2400 dpi, 16-bit, PNG | `detect.find_photos` |

Verified on a 35 mm strip at 2400 dpi and 16 bits: a 933 MB scan, four frames
found, 8.1 megapixel 16-bit crops out, fifteen seconds, 3.3 GB peak.

Three scanners measured, baselines in `quality/`: an HP Color LaserJet Pro
M478f, an Epson Perfection V500, an Epson Perfection 2400. **Use the V500.**
Both Epsons clip no black at all where the HP crushes 5% of its pixels to pure
black, and the V500 holds a third more shadow detail than the 2400 and 30% less
lid noise.

## What is next

Nothing is blocked. In rough order of value:

- **Downstream processing.** Contrast and colour work, dust removal, whatever
  else. The architecture is already pointed at it: scan as raw and as deep as
  the hardware allows, keep that, correct afterwards. A correction that turns
  out wrong then costs a re-run rather than a re-scan.
- **Slide crops run a hair wide** into the mount — 65 to 100% of their border
  pixels are mount rather than picture. The trim tolerance was tuned against a
  white lid and slides sit on black. Cosmetic; the pictures are complete.
- **The dust map is recorded and never used.** The app knows where the dirt on
  the glass is and could flag a speck that lands inside a crop, or heal it.
  Note it goes stale the moment anyone cleans the glass, so anything acting on
  it should check the date it carries.

## Traps worth knowing

- **A film scan that never starts is almost always the document mat.** The
  transparency lamp is in the lid, under the mat, and with the mat left in the
  driver reports no error at all — it selects the unit, says it is scanning,
  and waits forever. Twenty-seven minutes of that cost nothing but time. The
  app now says so after ninety seconds and gives up on a budget.
- **Do not kill a scan process.** It leaves the driver holding the session and
  the scanner blinking an error light, refusing the next scan until it is
  power-cycled. Let it time out, or call `ScanSession.give_up`, which closes
  the session on the way out.
- **A bed that darkens towards an edge welds prints together.** Every scanner
  vignettes: the V500 is dark until 0.33 in from its left edge, the 2400 until
  0.57 in. That margin reads as "not background" down the whole bed, so prints
  in it are bridged into one blob however much space is between them — it looks
  like a spacing problem and is not. Measure a new scanner with
  `tools/scan_blank.py` and keep prints clear of what it reports.
- **Edge rise does not measure sharpness.** Three scanners rank backwards
  against their own optics on it. `quality/README.md` explains why before
  someone reads it that way again.
- **Tonal figures only compare across scans holding the same originals.**
  Shadow, highlight, clipping and saturation describe the photographs, not the
  scanner.
- **Film frames cannot be found by texture.** A frame of empty sky is flatter
  than the rebate lines either side of it, so anything keying on variance eats
  it. Brightness is the discriminator: unexposed base is the thinnest part of a
  negative and reads the same at every gap.
- **`--min-size` silently discards film.** A 35 mm frame is 0.94 in on its
  short side and the print default is 1.0. The failure looks like "no photos
  found", not like a threshold.
- **Compressed air makes a flatbed dirtier.** It lifts dust out of the housing
  onto the glass — measured at 49 specks before and 98 after. A microfibre
  cloth works; calibrate before and after and the numbers will tell you.
- **Colour on old film is approximate.** A home-processed roll and a
  professionally processed one, inverted by identical code, come out visibly
  different; the difference is in the film. Do not tune the inversion until one
  particular strip looks right — that encodes one roll's degradation into the
  tool.
- **Memory is the ceiling, not resolution.** 2400 dpi film peaks at 3.3 GB.
  3200 would be about 5.6 GB and 6400 about 22 GB, so 2400 is near the
  practical limit on a 16 GB machine whatever the scanner advertises.
- **The scannable area is smaller than the glass.** Photosplit flags photos
  that reach the boundary; heed it. Check a new scanner with
  `tools/scanner_info.py`.
- Photosplit straightens photographs but cannot know which way is up. One laid
  sideways is saved sideways.
- Tests must never touch the installed app's preferences. `Prefs` takes a suite
  name and the tests point it at a throwaway domain; keep it that way. They
  also turn off "reveal when done", or every run leaves Finder windows behind.

## Setting up on another Mac

```bash
git clone <this repo> photosplit
cd photosplit && ./install.sh
```

The path is only a convention; anywhere works. If the repo is moved after
install, re-run `./install.sh` — the virtualenv, the `~/.local/bin` symlink and
the app bundle all hold absolute paths and break silently until it reruns.

The virtualenv is built per machine — never copy `.venv` between them. It is
also 210 MB of the repo's 212, almost all of it OpenCV, and entirely
disposable: deleting it costs one run of `install.sh`. Both an Apple Silicon
and an Intel Mac work; macOS 11 or newer.

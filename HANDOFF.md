# Handoff

Everything a fresh session needs to pick this up, on this machine or another.
The conversation that produced it does not travel; this file and the commit
history are the record.

## What this is

Photosplit scans a flatbed and saves each photograph on it as its own cropped,
straightened file. It handles prints on the glass, strips of film, and mounted
slides, inverts negatives, and can take dust off what it produces. It drives
the scanner through macOS's ImageCaptureCore, so any scanner that works in
Image Capture works here.

Read `README.md` first for how to use it, then `git log` — the commit messages
carry the reasoning behind every non-obvious decision, including the ones that
were wrong first, and there have been several.

## Where things stand

All three media work end to end against real hardware. 133 tests pass, and
`build_app.sh` builds the interface inside the finished bundle and fails if it
cannot start there.

| Mode | Unit | Default | Detector |
| --- | --- | --- | --- |
| Prints | flatbed | 600 dpi, 16-bit, PNG | `detect.find_photos` |
| Film | positive transparency | 2400 dpi, 16-bit, PNG, inverted | `film.find_frames` |
| Slides | positive transparency | 2400 dpi, 16-bit, PNG | `detect.find_photos` |

Verified on a 35 mm strip at 2400 dpi and 16 bits: a 933 MB scan, four frames,
8.1 megapixel 16-bit crops out, fifteen seconds, 3.3 GB peak. Verified again on
a strip of TMAX 400, which found a real bug (see the traps).

Preferences is two pages. **Scanning** is how a scan is made; **Post-Processing**
is what is done to it afterwards — inverting, dust, and a free-text note written
into every PNG. Every setting on both pages belongs to the selected mode.

Three scanners measured, baselines in `quality/`: an HP Color LaserJet Pro
M478f, an Epson Perfection V500, an Epson Perfection 2400. **Use the V500.**

## What is next

Nothing is blocked.

- **Look at a dust preview at full resolution.** `--dust-preview` rings what
  would be removed instead of removing it. It has been eyeballed downscaled,
  which says where the specks are and not whether each really is one. Do that
  before running removal over anything irreplaceable.
- **The dust map is recorded and still unused.** Glass dirt sits at known
  positions, so those specks could be healed with no detection risk at all —
  the safest source there is, and the reason calibration writes the map. It
  goes stale the moment the glass is cleaned, so anything acting on it should
  check the date it carries.
- **More post-processing.** Contrast and colour work. The page exists for it,
  and the home-processed roll is the case that needs it.

## Traps worth knowing

- **A film scan that never starts is almost always the document mat.** The
  transparency lamp is in the lid, under the mat, and with the mat left in the
  driver reports no error at all — it selects the unit, says it is scanning,
  and waits forever. The app now says so after ninety seconds and gives up on
  a budget.
- **Do not kill a scan process.** It leaves the driver holding the session and
  the scanner blinking, refusing the next scan until it is power-cycled. Let it
  time out, or call `ScanSession.give_up`, which closes the session.
- **Infrared cleaning is not available and cannot be made available.**
  ImageCaptureCore has no infrared pixel type and no infrared functional unit,
  so no driver can deliver it through that API however good. Epson ships no
  Scan application for this model on current macOS, only an ICA driver, and
  macOS removed TWAIN years ago. It would not have helped for TMAX anyway:
  silver-based film is opaque to infrared and the whole frame reads as defect.
- **Dust detection defaults to light, and should stay that way.** Checked at
  1:1 on a TMAX 400 frame: normal found fourteen candidates of which four were
  plainly dust and five sat on a jumper's knit with nothing visibly wrong;
  light found five of which four were plainly dust. Judge any change to this
  at 1:1 on real film, not downscaled — every earlier look was downscaled and
  said nothing useful about which detections were real.
- **Dust cannot be told from grain below about 1200 dpi.** The setting greys
  out under that. On a 600 dpi frame of a lawn what the detector finds is the
  clover.
- **Size in pixels is the wrong unit for dust.** The same film at 600 and 2400
  dpi yields blobs of the same 4 px median area; a real speck covers sixteen
  times the area at four times the sampling. Size that does not scale with
  resolution is grain.
- **A rebate line is only flat relative to its own film.** Six absolute levels
  fits fine colour film at 600 dpi and fails TMAX 400 at 2400, whose rebate
  measured 7.4 while its frames ran 15 to 28 — the whole strip came back as one
  frame. The limit is taken from the strip now.
- **Film frames cannot be found by texture.** A frame of empty sky is flatter
  than the rebate lines beside it. Brightness is the discriminator.
- **`--min-size` silently discards film.** A 35 mm frame is 0.94 in on its
  short side and the print default is 1.0. It looks like "no photos found".
- **A bed that darkens towards an edge welds prints together**, however much
  space is between them. Measure a new scanner with `tools/scan_blank.py`.
- **Edge rise does not measure sharpness.** Three scanners rank backwards
  against their own optics on it; `quality/README.md` explains why.
- **Tonal figures only compare across scans of the same originals.**
- **Colour on old film is approximate.** A home-processed roll and a
  professionally processed one, inverted by identical code, come out visibly
  different, and the difference is in the film. Never tune the inversion until
  one particular strip looks right.
- **Nothing is a constant that can be measured instead.** The orange mask, the
  lid colour, the rebate flatness, the noise floor: every one of these differs
  between rolls, scanners and machines, and every time one was assumed it was
  wrong for something. Measure it from the thing in hand.
- **Compressed air makes a flatbed dirtier** — 49 specks before, 98 after. Use
  a microfibre cloth and calibrate either side of it.
- **Memory is the ceiling, not resolution.** 2400 dpi film peaks at 3.3 GB;
  3200 would be about 5.6 and 6400 about 22, so 2400 is near the practical
  limit on a 16 GB machine whatever the scanner advertises.
- **Per-mode settings have flat namesakes that are no longer read.**
  `prefs["resolution"]` still exists for migration and is not what a scan uses;
  `prefs.get("resolution")` is. Reading the wrong one put a stale number in the
  main window that never changed when the mode did.
- Photosplit straightens photographs but cannot know which way is up.
- Tests must never touch the installed app's preferences, and must leave no
  Finder windows or temporary folders behind. All three are pinned by tests.

## Setting up on another Mac

```bash
git clone <this repo> photosplit
cd photosplit && ./install.sh
```

The path is only a convention. If the repo is moved after install, re-run
`./install.sh` — the virtualenv, the `~/.local/bin` symlink and the app bundle
all hold absolute paths and break silently until it reruns.

The virtualenv is built per machine — never copy `.venv` between them. It is
also 210 MB of the repo's 212, almost all of it OpenCV, and entirely
disposable. Both an Apple Silicon and an Intel Mac work; macOS 11 or newer.

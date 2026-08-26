# Scan quality baselines

Numbers from `tools/scan_quality.py`, kept so a second scanner can be compared
against the first without rescanning.

| File | Scanner | Resolution | Photos |
| --- | --- | --- | --- |
| `hp-m478f-300dpi.json` | HP Color LaserJet Pro M478f | 300 | 6 |
| `hp-m478f-600dpi.json` | HP Color LaserJet Pro M478f | 600 | 5 |
| `hp-m478f-1200dpi.json` | HP Color LaserJet Pro M478f | 1200 | 5 |
| `hp-m478f-all.json` | all three HP scans together | | |

**The two HP scans hold different prints** — one was removed between them — so
their tonal figures (shadow, highlight, clipping, saturation) describe
different subjects and must not be compared. The lid figures measure the
scanner rather than the prints and compare cleanly regardless.

What the HP established, for the Epson to be judged against:

- Lid neutrality is good: colour cast 0.73 at 300 dpi, 0.30 at 600.
- Lid noise 1.44 at 300 dpi, 1.07 at 600.
- **Shadows are crushed: 4-5% of pixels sit at pure black at both resolutions,
  with the 1st percentile at 0.0.** This is the HP's clearest weakness and the
  first thing to check on a dedicated photo scanner.
- 600 dpi resolves genuinely more than 300, and 1200 more than 600. Measured on
  the same physical patch of the same print, expressed in cycles per millimetre,
  the 1200 dpi spectrum decays smoothly across the 600 dpi Nyquist (11.8 c/mm)
  rather than falling off a cliff, so none of it is interpolated. The content up
  there is faint — two to three orders below the low frequencies, and mostly
  paper grain rather than picture.
- **Optical edge spread is about 150 um.** This only becomes measurable at 1200
  dpi. At 300 and 600 the figure came out at exactly 2 pixels both times, which
  is the sampling floor rather than a property of the scanner.

## Comparing optics between scanners

Compare edge rise **at 1200 dpi on both machines**. Below that the pixel grid,
not the lens, sets the number. Everything else compares at any matched
resolution.

## Cost of each resolution on the HP

| Resolution | Scan time | Full-bed TIFF | 6x4 print as PNG | Peak memory |
| --- | --- | --- | --- | --- |
| 300 dpi | 13 s | 10 MB | 2 MB | modest |
| 600 dpi | 18 s | 28 MB | 8 MB | modest |
| 1200 dpi | 43 s | 98 MB | 30 MB | 2.9 GB |

To compare a new scanner, put the same prints on its glass in the same places
and run:

```bash
.venv/bin/python tools/scan_quality.py "path/to/new-scan.tiff" \
    --json quality/epson-v500-600dpi.json
```

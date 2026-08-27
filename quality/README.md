# Scan quality baselines

Numbers from `tools/scan_quality.py`, kept so a second scanner can be compared
against the first without rescanning.

| File | Scanner | Resolution | Photos |
| --- | --- | --- | --- |
| `hp-m478f-300dpi.json` | HP Color LaserJet Pro M478f | 300 | 6 |
| `hp-m478f-600dpi.json` | HP Color LaserJet Pro M478f | 600 | 5 |
| `hp-m478f-1200dpi.json` | HP Color LaserJet Pro M478f | 1200 | 5 |
| `hp-m478f-all.json` | all three HP scans together | | |
| `epson-v500-600dpi.json` | Epson Perfection V500 | 600 | 5 |
| `epson-v500-1200dpi.json` | Epson Perfection V500 | 1200 | 5 |
| `epson-2400-600dpi.json` | Epson Perfection 2400 | 600 | 5 |
| `epson-2400-1200dpi.json` | Epson Perfection 2400 | 1200 | 5 |

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
- **Edge spread is about 150 um at 1200 dpi.** At 300 and 600 the figure came
  out at exactly 2 pixels both times, which is the sampling floor rather than a
  property of the scanner. This was once read as the HP being optically sharper
  than both Epsons; see "Comparing optics between scanners" below for why that
  reading is wrong.

## Comparing optics between scanners

**Edge rise does not measure resolving power. Do not read it as sharpness.**

Three scanners settled this, and the ranking comes out backwards against
optical resolution:

| Scanner | Native optical | Edge rise at 1200 dpi |
| --- | --- | --- |
| HP M478f | 1200 dpi, the lowest | 148.2 um, the best |
| Epson V500 | 6400 dpi, the highest | 275.2 um |
| Epson 2400 | 2400 dpi | 296.3 um |

Two Epson CCDs 2.7x apart in optics land within 8% of each other, while the
scanner with the worst optics of the three measures twice as sharp. The
figures are real -- they hold in microns as the pixel count doubles, so they
are not the sampling floor -- but what they track is how abruptly a scanner
renders the edge of a **thick object**. That is illumination geometry: the HP
lights the paper edge from the sensor line, both Epsons cast a shadow ramp
into it. It says nothing about the lens.

Measuring real resolving power needs a slanted edge on a thin flat target,
which nothing here does. Until something does, compare edge rise only between
scanners of the same sensor family, and never call it sharpness.

Everything else compares at any matched resolution.

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

## What the Epsons settled

Both Epsons beat the HP on the only question that matters for photographs.
Where the HP crushes 5.3% of its pixels to pure black with the 1st percentile
at 0.0, both Epsons clip nothing at all:

| At 1200 dpi | HP M478f | Epson V500 | Epson 2400 |
| --- | --- | --- | --- |
| shadow detail (p1) | 0.0 | 35.1 | 26.3 |
| clipped black | 5.33% | 0.000% | 0.000% |
| shadow noise | 6.13 | 4.02 | 3.55 |
| lid noise | 1.10 | 2.90 | 3.77 |
| lid cast | 0.30 | 6.91 | 5.04 |

The HP's higher saturation and p99 are not quality; they are the same steep
curve that is destroying its shadows.

Between the two Epsons the V500 wins, though not by much: a third more shadow
detail (35.1 against 26.3), 30% less lid noise, 6400 dpi native against 2400,
and faster at 1200. The 2400 genuinely wins on shadow noise (3.55 against
4.02) -- the V500 lifts shadows harder, recovering more detail and more grain
with it -- and on lid cast, which `--neutralise` corrects on either machine.

**Use the V500.** The 2400 also vignettes twice as deep along its left edge,
0.57 in against 0.33 in, which defeats photo detection every time the glass is
loaded unless prints are kept clear of it.

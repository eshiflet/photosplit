# Scan quality baselines

Numbers from `tools/scan_quality.py`, kept so a second scanner can be compared
against the first without rescanning.

| File | Scanner | Resolution | Photos |
| --- | --- | --- | --- |
| `hp-m478f-300dpi.json` | HP Color LaserJet Pro M478f | 300 | 6 |
| `hp-m478f-600dpi.json` | HP Color LaserJet Pro M478f | 600 | 5 |
| `hp-m478f-300-vs-600.json` | both of the above together | | |

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
- 600 dpi resolves genuinely more than 300: the power spectrum continues past
  the 300 dpi Nyquist with no cliff, so the extra samples are not interpolated.

To compare a new scanner, put the same prints on its glass in the same places
and run:

```bash
.venv/bin/python tools/scan_quality.py "path/to/new-scan.tiff" \
    --json quality/epson-v500-600dpi.json
```

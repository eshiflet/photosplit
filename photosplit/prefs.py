"""Preferences, stored where every other Mac app stores them: NSUserDefaults."""

from __future__ import annotations

from pathlib import Path

from Foundation import NSUserDefaults

SUITE = "com.ericshiflet.photosplit"

DEFAULTS: dict[str, object] = {
    "outputFolder": str(Path.home() / "Pictures" / "Photosplit"),
    "resolution": 600,
    "colour": True,
    "format": "jpg",
    "quality": 95,
    "minSize": 1.0,
    "deskew": True,
    "trim": True,
    "keepFullScan": False,
    "writePreview": False,
    "revealWhenDone": True,
    "scannerName": "",
}

FORMATS = ["jpg", "png", "tif"]
FORMAT_LABELS = ["JPEG", "PNG (lossless)", "TIFF (lossless)"]
RESOLUTIONS = [150, 200, 300, 400, 600, 1200]
# JPEG at 95 is already visually transparent — measured at ~49 dB PSNR against
# the uncompressed crop — but archival work sometimes wants the top of the range.
QUALITIES = [85, 90, 95, 98, 100]
QUALITY_LABELS = [
    "85 — smallest files",
    "90",
    "95 — recommended",
    "98",
    "100 — largest files",
]


class Prefs:
    """Thin typed wrapper so the rest of the app never touches raw defaults."""

    def __init__(self, suite: str | None = None) -> None:
        # Read SUITE at call time, not at import: the tests point this at a
        # throwaway domain so that running them cannot rewrite real settings.
        self._suite = suite or SUITE
        self._store = NSUserDefaults.alloc().initWithSuiteName_(self._suite)
        self._store.registerDefaults_(DEFAULTS)

    def __getitem__(self, key: str):
        value = self._store.objectForKey_(key)
        return DEFAULTS[key] if value is None else value

    def __setitem__(self, key: str, value) -> None:
        self._store.setObject_forKey_(value, key)

    @property
    def output_folder(self) -> Path:
        return Path(str(self["outputFolder"])).expanduser()

    def as_split_options(self):
        from .split import SplitOptions

        return SplitOptions(
            output_dir=self.output_folder,
            fmt=str(self["format"]),
            quality=int(self["quality"]),
            min_size=float(self["minSize"]),
            deskew=bool(self["deskew"]),
            trim=bool(self["trim"]),
            preview=bool(self["writePreview"]),
        )

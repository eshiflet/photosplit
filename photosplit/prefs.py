"""Preferences, stored where every other Mac app stores them: NSUserDefaults."""

from __future__ import annotations

from pathlib import Path

from Foundation import NSBundle, NSUserDefaults

SUITE = "com.photosplit.app"

# What is being scanned decides the functional unit, the resolution, the bit
# depth and how small a thing still counts as a picture, so each mode carries
# its own copy of those rather than one set being wrong for two of the three.
PRINT, FILM, SLIDE = "print", "film", "slide"
MODES = (PRINT, FILM, SLIDE)
MODE_LABELS = {PRINT: "Prints", FILM: "Film", SLIDE: "Slides"}
MODE_ACTIONS = {
    PRINT: "Run Print Scan",
    FILM: "Run Film Scan",
    SLIDE: "Run Slide Scan",
}

# Film and slides both go through the positive transparency unit, and they are
# still not the same job. A strip is one continuous ribbon of frames separated
# by a rebate line; slides are individual mounts, sitting apart, in a different
# holder that puts different geometry in the same window. What is scanned is
# alike, what has to be found in it is not.
#
# The unit is the positive one for both, never the negative one: that inverts
# as it scans and flattens the channels doing it -- a spread of 4.8 between
# them against 41.4 for the same frame taken positive, which is colour
# separation that cannot be got back. Inverting is downstream work on a scan
# that still holds everything the film does.

MODE_DEFAULTS: dict[str, dict[str, object]] = {
    # PNG throughout: lossless, holds 16 bits per channel, one format to think
    # about. 600 dpi is plenty for an opaque print.
    PRINT: {"resolution": 600, "bitDepth": 16, "format": "png", "minSize": 1.0, "invert": False},
    # Film is inverted afterwards, which stretches the shadows hard enough to
    # band 8-bit data. 2400 rather than the
    # 6400 the V500 advertises: a full strip at 6400 in 16-bit is 5.8 GB, and
    # the measured edge spread says the optics do not resolve anywhere near it.
    FILM: {
        "resolution": 2400, "bitDepth": 16, "format": "png", "minSize": 0.5,
        # Film strips are usually negatives; slide film in uncut strips is not,
        # so this is a setting rather than a consequence of the mode.
        "invert": True,
    },
    # A mounted 35 mm slide shows about 1.35 x 0.90 in through its mount.
    SLIDE: {"resolution": 2400, "bitDepth": 16, "format": "png", "minSize": 0.5, "invert": False},
}

# A 35 mm frame is 0.94 x 1.42 in, so the print default of 1.0 in would throw
# every one of them away as too small. Hence minSize per mode above.

DEFAULTS: dict[str, object] = {
    "outputFolder": str(Path.home() / "Pictures" / "Photosplit"),
    "scanMode": PRINT,
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
for _mode, _values in MODE_DEFAULTS.items():
    for _key, _value in _values.items():
        DEFAULTS[f"{_mode}.{_key}"] = _value

FORMATS = ["jpg", "png", "tif"]
FORMAT_LABELS = ["JPEG", "PNG (lossless)", "TIFF (lossless)"]
RESOLUTIONS = [150, 200, 300, 400, 600, 1200]
# Film is tiny, so it is scanned at resolutions that would be absurd for a
# print. The top of each list is what the hardware offers, not what is wise.
MODE_RESOLUTIONS = {
    PRINT: RESOLUTIONS,
    FILM: [1200, 2400, 3200, 4800, 6400],
    SLIDE: [1200, 2400, 3200, 4800, 6400],
}
BIT_DEPTHS = [8, 16]
BIT_DEPTH_LABELS = ["8-bit", "16-bit — keeps shadow detail through an inversion"]
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


def _open(suite: str) -> NSUserDefaults:
    """The defaults store for a suite name.

    A suite that matches the running app's own bundle identifier is refused by
    macOS and comes back nil — which is exactly the case inside Photosplit.app,
    and exactly the case that never arises when running from a script. The
    app's own identifier is what standardUserDefaults already is, so use that.
    """
    identifier = NSBundle.mainBundle().bundleIdentifier()
    if identifier and suite == identifier:
        return NSUserDefaults.standardUserDefaults()
    return NSUserDefaults.alloc().initWithSuiteName_(suite) or (
        NSUserDefaults.standardUserDefaults()
    )


class Prefs:
    """Thin typed wrapper so the rest of the app never touches raw defaults."""

    # Settings that used to belong to the app and now belong to a mode. An
    # install from before the modes existed has these sitting in its defaults,
    # and they were chosen for prints, because prints were all there was.
    MOVED = ("resolution", "format", "minSize")

    def __init__(self, suite: str | None = None) -> None:
        # Read SUITE at call time, not at import: the tests point this at a
        # throwaway domain so that running them cannot rewrite real settings.
        self._suite = suite or SUITE
        self._store = _open(self._suite)
        self._store.registerDefaults_(DEFAULTS)
        self._adopt_settings_from_before_modes()

    def _adopt_settings_from_before_modes(self) -> None:
        """Carry pre-mode settings into the print mode, once.

        Only what was actually saved: the registration domain answers for
        every key whether or not anyone chose it, so asking objectForKey_
        would migrate the defaults over the top of themselves forever.
        """
        saved = self._store.persistentDomainForName_(self._suite) or {}
        for key in self.MOVED:
            target = f"{PRINT}.{key}"
            if key in saved and target not in saved:
                self._store.setObject_forKey_(saved[key], target)

    def __getitem__(self, key: str):
        value = self._store.objectForKey_(key)
        return DEFAULTS[key] if value is None else value

    def __setitem__(self, key: str, value) -> None:
        self._store.setObject_forKey_(value, key)

    @property
    def output_folder(self) -> Path:
        return Path(str(self["outputFolder"])).expanduser()

    @property
    def mode(self) -> str:
        chosen = str(self["scanMode"])
        return chosen if chosen in MODES else PRINT

    @mode.setter
    def mode(self, value: str) -> None:
        self["scanMode"] = value if value in MODES else PRINT

    def get(self, key: str, mode: str | None = None):
        """A setting belonging to one mode rather than to the app."""
        return self[f"{mode or self.mode}.{key}"]

    def set(self, key: str, value, mode: str | None = None) -> None:
        self[f"{mode or self.mode}.{key}"] = value

    @property
    def unit(self) -> int:
        from .scanner import FLATBED, POSITIVE

        # Film and slides alike go through the positive unit: it is the one
        # that hands back what is actually on the film.
        return {PRINT: FLATBED, FILM: POSITIVE, SLIDE: POSITIVE}[self.mode]

    def as_split_options(self):
        from .split import SplitOptions

        return SplitOptions(
            output_dir=self.output_folder,
            fmt=str(self.get("format")),
            quality=int(self["quality"]),
            min_size=float(self.get("minSize")),
            deskew=bool(self["deskew"]),
            trim=bool(self["trim"]),
            preview=bool(self["writePreview"]),
            strip=self.mode == FILM,
            invert=bool(self.get("invert")),
        )

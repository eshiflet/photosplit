"""Drive a flatbed scanner through macOS's own ImageCaptureCore framework.

This is the same plumbing Image Capture.app uses, so any scanner that works
there works here, with no extra driver. Everything in ImageCaptureCore is
asynchronous and delegate-driven: a scan is a chain of callbacks that runs
open session -> become ready -> select flatbed -> configure -> scan -> close.
`ScanSession` hides that chain behind two callbacks, `on_status` and `on_done`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import ImageCaptureCore as ICC
import objc
from Foundation import NSURL, NSDate, NSMakeRect, NSObject, NSRunLoop

FLATBED = ICC.ICScannerFunctionalUnitTypeFlatbed
POSITIVE = ICC.ICScannerFunctionalUnitTypePositiveTransparency
NEGATIVE = ICC.ICScannerFunctionalUnitTypeNegativeTransparency
DOCUMENT_UTI = "public.tiff"  # lossless hand-off to the splitter


@dataclass
class ScanSettings:
    resolution: int = 300
    colour: bool = True
    downloads_dir: Path = Path("/tmp")
    document_name: str = "scan"
    # Film is a different unit, not a different setting: its own lamp, its own
    # geometry, its own much smaller window. On a V500 the flatbed is
    # 8.5 x 11.7 in and either transparency unit is 2.7 x 9.33 in.
    unit: int = FLATBED
    # 8 is plenty for a print. A negative is inverted after scanning, which
    # stretches the shadows hard enough to band 8-bit data visibly.
    bit_depth: int = 8


class ScannerHub(NSObject):
    """Watches for scanners appearing and disappearing on USB and the network."""

    def initWithCallback_(self, on_change: Callable[[list], None]):
        self = objc.super(ScannerHub, self).init()
        if self is None:
            return None
        self._on_change = on_change
        self._browser = ICC.ICDeviceBrowser.alloc().init()
        self._browser.setDelegate_(self)
        self._browser.setBrowsedDeviceTypeMask_(
            ICC.ICDeviceTypeMaskScanner
            | ICC.ICDeviceLocationTypeMaskLocal
            | ICC.ICDeviceLocationTypeMaskShared
            | ICC.ICDeviceLocationTypeMaskBonjour
        )
        return self

    def start(self) -> None:
        self._browser.start()

    def stop(self) -> None:
        self._browser.stop()

    def scanners(self) -> list:
        return [d for d in (self._browser.devices() or []) if isinstance(d, ICC.ICScannerDevice)]

    # -- ICDeviceBrowserDelegate ------------------------------------------
    def deviceBrowser_didAddDevice_moreComing_(self, browser, device, more) -> None:
        if not more:
            self._on_change(self.scanners())

    def deviceBrowser_didRemoveDevice_moreGoing_(self, browser, device, more) -> None:
        if not more:
            self._on_change(self.scanners())


class ScanSession(NSObject):
    """One scan, start to finish, on one device."""

    def initWithDevice_settings_status_done_(
        self,
        device,
        settings: ScanSettings,
        on_status: Callable[[str], None],
        on_done: Callable[[Path | None, str | None], None],
    ):
        self = objc.super(ScanSession, self).init()
        if self is None:
            return None
        self._device = device
        self._settings = settings
        self._on_status = on_status
        self._on_done = on_done
        self._result: Path | None = None
        self._finished = False
        self._actual_resolution = settings.resolution
        self._expected_mpx = 0.0
        return self

    @objc.python_method
    def give_up(self, reason: str) -> None:
        """Abandon a scan, closing the session behind it.

        A client that simply stops listening leaves the scanner mid-scan with
        its session open, and it stays that way — blinking an error light and
        refusing the next scan — until someone power-cycles it.
        """
        self._fail(reason)

    @objc.python_method
    def expected_megapixels(self) -> float:
        """How big this scan should be, for judging how long it may take."""
        return self._expected_mpx

    @objc.python_method
    def actual_resolution(self) -> int:
        """The resolution the hardware really used, which may not be the one asked for."""
        return self._actual_resolution

    def start(self) -> None:
        self._on_status(f"Opening {self._device.name()}…")
        self._device.setDelegate_(self)
        self._device.requestOpenSession()

    @objc.python_method
    def _fail(self, message: str) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            self._device.requestCloseSession()
        except Exception:
            pass
        self._on_done(None, message)

    @objc.python_method
    def _succeed(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._device.requestCloseSession()
        self._on_done(self._result, None)

    # -- ICDeviceDelegate --------------------------------------------------
    def device_didOpenSessionWithError_(self, device, error) -> None:
        if error is not None:
            self._fail(f"Could not open the scanner: {error.localizedDescription()}")

    def deviceDidBecomeReady_(self, device) -> None:
        self._on_status(f"Selecting the {unit_name(self._settings.unit)}…")
        device.requestSelectFunctionalUnit_(self._settings.unit)

    def device_didCloseSessionWithError_(self, device, error) -> None:
        pass

    def didRemoveDevice_(self, device) -> None:
        self._fail("The scanner was unplugged or went offline.")

    def device_didEncounterError_(self, device, error) -> None:
        if error is not None:
            self._fail(error.localizedDescription())

    # -- ICScannerDeviceDelegate ------------------------------------------
    def scannerDevice_didSelectFunctionalUnit_error_(self, device, unit, error) -> None:
        wanted = self._settings.unit
        if error is not None:
            return self._fail(
                f"This scanner has no {unit_name(wanted)}: {error.localizedDescription()}"
            )
        # A scanner reports each unit as it settles; ignore the ones not asked for.
        if unit is None or unit.type() != wanted:
            return
        try:
            self._configure(device, unit)
        except Exception as problem:  # a scanner that refuses a setting
            return self._fail(f"Could not configure the scanner: {problem}")
        self._on_status(f"Scanning at {self._settings.resolution} dpi…")
        device.requestScan()

    @objc.python_method
    def _configure(self, device, unit) -> None:
        settings = self._settings
        unit.setMeasurementUnit_(ICC.ICScannerMeasurementUnitInches)

        supported = unit.supportedResolutions()
        wanted = settings.resolution
        if supported is not None and not supported.containsIndex_(wanted):
            wanted = _nearest(supported, wanted)
            self._on_status(f"{settings.resolution} dpi unsupported; using {wanted} dpi")
        unit.setResolution_(wanted)
        self._actual_resolution = wanted

        unit.setPixelDataType_(
            ICC.ICScannerPixelDataTypeRGB if settings.colour else ICC.ICScannerPixelDataTypeGray
        )
        unit.setBitDepth_(_depth(unit, settings.bit_depth, self._on_status))

        # Always take the whole window: originals can be anywhere in it, and
        # what "the whole window" means depends on the unit that was selected.
        size = unit.physicalSize()
        unit.setScanArea_(NSMakeRect(0, 0, size.width, size.height))

        self._expected_mpx = size.width * size.height * wanted * wanted / 1e6

        settings.downloads_dir.mkdir(parents=True, exist_ok=True)
        device.setDownloadsDirectory_(
            NSURL.fileURLWithPath_(str(settings.downloads_dir))
        )
        device.setDocumentName_(settings.document_name)
        device.setDocumentUTI_(DOCUMENT_UTI)

    def scannerDevice_didScanToURL_(self, device, url) -> None:
        self._result = Path(url.path())

    def scannerDevice_didScanToURL_data_(self, device, url, data) -> None:
        self._result = Path(url.path())

    def scannerDevice_didCompleteScanWithError_(self, device, error) -> None:
        if error is not None:
            return self._fail(f"The scan failed: {error.localizedDescription()}")
        if self._result is None:
            return self._fail("The scanner reported success but produced no file.")
        self._succeed()


UNIT_NAMES = {FLATBED: "flatbed", POSITIVE: "slide unit", NEGATIVE: "negative unit"}


def unit_name(unit: int) -> str:
    return UNIT_NAMES.get(unit, "scanner")


def _depth(unit, wanted: int, on_status) -> int:
    """The bit depth asked for, or the deepest the hardware will give.

    Falling back to 8 quietly would be the wrong way round: the whole reason
    to ask for 16 is film, and film is where losing it shows.
    """
    supported = unit.supportedBitDepths()
    if supported is None or supported.containsIndex_(wanted):
        return wanted
    for option in (16, 8):
        if supported.containsIndex_(option):
            on_status(f"{wanted}-bit unsupported; using {option}-bit")
            return option
    return wanted


def _nearest(index_set, wanted: int) -> int:
    """Closest resolution the hardware actually offers."""
    options = []
    index = index_set.firstIndex()
    while index != ICC.NSNotFound and index < 10_000:
        options.append(int(index))
        index = index_set.indexGreaterThanIndex_(index)
    return min(options, key=lambda r: abs(r - wanted)) if options else wanted


def run_loop_until(predicate: Callable[[], bool], timeout: float) -> bool:
    """Pump the run loop so ImageCaptureCore callbacks fire outside of AppKit."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )
    return predicate()

"""Report what a scanner can actually do: its reachable area and resolutions.

Useful when a photo that was definitely on the glass still came out clipped.
The glass is often larger than the area the sensor can reach, and this prints
the difference rather than leaving it to guesswork.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import ImageCaptureCore as ICC
import objc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photosplit.scanner import (  # noqa: E402
    ScannerHub,
    ScanSession,
    ScanSettings,
    run_loop_until,
)

FLATBED = ICC.ICScannerFunctionalUnitTypeFlatbed


class Probe(ScanSession):
    """Opens the scanner, reports the flatbed's limits, and stops before scanning."""

    def scannerDevice_didSelectFunctionalUnit_error_(self, device, unit, error):
        if error is not None:
            print(f"  could not select the flatbed: {error.localizedDescription()}")
            self._finished = True
            return
        if unit is None or unit.type() != FLATBED:
            return

        unit.setMeasurementUnit_(ICC.ICScannerMeasurementUnitInches)
        size = unit.physicalSize()
        print(f"  maximum scan area : {size.width:.2f} x {size.height:.2f} in")
        print(f"                      ({size.width * 25.4:.0f} x {size.height * 25.4:.0f} mm)")

        for name, w, h in (("Letter", 8.5, 11.0), ("A4", 8.27, 11.69)):
            fits = "yes" if size.width >= w - 0.01 and size.height >= h - 0.01 else "NO"
            print(f"  covers {name:7s}    : {fits}")

        options = []
        supported = unit.supportedResolutions()
        if supported is not None:
            index = supported.firstIndex()
            while index != ICC.NSNotFound and index < 10_000:
                options.append(int(index))
                index = supported.indexGreaterThanIndex_(index)
        print(f"  resolutions       : {options}")
        print(f"  native resolution : {unit.nativeXResolution()} x {unit.nativeYResolution()}")

        # Ask for the whole bed and see what the scanner grants; a device that
        # silently shrinks the request is the thing worth catching here.
        from Foundation import NSMakeRect

        unit.setScanArea_(NSMakeRect(0, 0, size.width, size.height))
        granted = unit.scanArea()
        print(
            f"  requested whole bed -> granted "
            f"{granted.size.width:.2f} x {granted.size.height:.2f} in "
            f"at origin ({granted.origin.x:.2f}, {granted.origin.y:.2f})"
        )
        device.requestCloseSession()
        self._finished = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Report each scanner's reachable area.")
    parser.add_argument("--wait", type=float, default=12.0, help="seconds to look for scanners")
    args = parser.parse_args()

    seen: list = []
    hub = ScannerHub.alloc().initWithCallback_(lambda d: seen.append(d))
    hub.start()
    run_loop_until(lambda: False, args.wait)

    devices = hub.scanners()
    if not devices:
        print("no scanners found")
        return 1

    for device in devices:
        print(f"\n{device.name()}  [{device.transportType()}]")
        probe = Probe.alloc().initWithDevice_settings_status_done_(
            device, ScanSettings(), lambda _t: None, lambda _p, _e: None
        )
        probe.start()
        run_loop_until(lambda: probe._finished, 40.0)
    hub.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

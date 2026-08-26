"""Checks on the app's window, its controls, and its preferences round-trip.

These build the real windows offscreen. They do not run the event loop, so no
window ever appears; what they verify is that every control the app depends on
exists, is wired to an action, and stays readable in dark mode.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from AppKit import (
    NSAppearance,
    NSAppearanceNameAqua,
    NSAppearanceNameDarkAqua,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSButton,
    NSColor,
    NSPopUpButton,
)

from photosplit.app import AppDelegate, PreferencesWindow
from photosplit.prefs import FORMATS, RESOLUTIONS

NSApplication.sharedApplication().setActivationPolicy_(
    NSApplicationActivationPolicyAccessory
)


class FakeDevice:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


def build_delegate() -> AppDelegate:
    delegate = AppDelegate.alloc().init()
    delegate._build_menu()
    delegate._build_window()
    delegate.prefs_window = None
    return delegate


def titles(popup: NSPopUpButton) -> list[str]:
    return list(popup.itemTitles())


def luminance(color: NSColor, appearance_name: str) -> float:
    """Resolve a dynamic system colour the way it will actually be drawn."""
    resolved = {}
    appearance = NSAppearance.appearanceNamed_(appearance_name)

    def draw() -> None:
        rgb = color.colorUsingColorSpaceName_("NSCalibratedRGBColorSpace")
        resolved["value"] = (
            0.2126 * rgb.redComponent()
            + 0.7152 * rgb.greenComponent()
            + 0.0722 * rgb.blueComponent()
        )

    appearance.performAsCurrentDrawingAppearance_(draw)
    return resolved["value"]


class WindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.delegate = build_delegate()

    def test_window_exists_with_a_scan_button_bound_to_an_action(self) -> None:
        self.assertEqual(self.delegate.window.title(), "Photosplit")
        button = self.delegate.scan_button
        self.assertIsInstance(button, NSButton)
        self.assertEqual(button.title(), "Scan")
        self.assertEqual(button.action(), "scan:")
        self.assertEqual(button.keyEquivalent(), "\r")

    def test_scan_button_is_disabled_until_a_scanner_appears(self) -> None:
        self.assertFalse(self.delegate.scan_button.isEnabled())
        self.delegate._devices_changed([FakeDevice("EPSON Perfection V500")])
        self.assertTrue(self.delegate.scan_button.isEnabled())
        self.assertIn("EPSON Perfection V500", titles(self.delegate.device_popup))

    def test_losing_the_scanner_disables_scanning_again(self) -> None:
        self.delegate._devices_changed([FakeDevice("EPSON Perfection V500")])
        self.delegate._devices_changed([])
        self.assertFalse(self.delegate.scan_button.isEnabled())
        self.assertIn("No scanner found", titles(self.delegate.device_popup))

    def test_remembered_scanner_is_reselected(self) -> None:
        self.delegate.prefs["scannerName"] = "EPSON Perfection V500"
        self.delegate._devices_changed(
            [FakeDevice("HP Color LaserJet"), FakeDevice("EPSON Perfection V500")]
        )
        self.assertEqual(
            self.delegate.device_popup.titleOfSelectedItem(), "EPSON Perfection V500"
        )

    def test_busy_state_blocks_a_second_scan(self) -> None:
        self.delegate._devices_changed([FakeDevice("EPSON Perfection V500")])
        self.delegate._set_busy(True, "Scanning…")
        self.assertFalse(self.delegate.scan_button.isEnabled())
        self.assertFalse(self.delegate.progress.isHidden())
        self.delegate._set_busy(False, "done")
        self.assertTrue(self.delegate.scan_button.isEnabled())
        self.assertTrue(self.delegate.progress.isHidden())

    def test_log_stays_readable_in_both_appearances(self) -> None:
        view = self.delegate.log_view
        for appearance in (NSAppearanceNameAqua, NSAppearanceNameDarkAqua):
            text = luminance(view.textColor(), appearance)
            back = luminance(view.backgroundColor(), appearance)
            self.assertGreater(
                abs(text - back), 0.4, f"log text is unreadable in {appearance}"
            )

    def test_log_appends_lines(self) -> None:
        self.delegate._log("first")
        self.delegate._log("second")
        self.assertIn("first\nsecond", str(self.delegate.log_view.string()))


class PreferencesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.delegate = build_delegate()
        self.prefs_window = PreferencesWindow.alloc().initWithPrefs_owner_(
            self.delegate.prefs, self.delegate
        )

    def test_every_control_is_offered(self) -> None:
        self.assertEqual(
            titles(self.prefs_window.res_popup), [f"{r} dpi" for r in RESOLUTIONS]
        )
        self.assertEqual(titles(self.prefs_window.fmt_popup), ["JPEG", "PNG", "TIFF"])

    def test_changing_a_control_persists_and_reaches_the_split_options(self) -> None:
        window = self.prefs_window
        window.res_popup.selectItemAtIndex_(RESOLUTIONS.index(600))
        window.fmt_popup.selectItemAtIndex_(FORMATS.index("png"))
        window.trim_box.setState_(0)
        window.changed_(None)

        prefs = self.delegate.prefs
        self.assertEqual(int(prefs["resolution"]), 600)
        self.assertEqual(str(prefs["format"]), "png")
        options = prefs.as_split_options()
        self.assertEqual(options.fmt, "png")
        self.assertFalse(options.trim)

    def test_reloading_shows_what_was_saved(self) -> None:
        self.delegate.prefs["resolution"] = 1200
        self.prefs_window._load()
        self.assertEqual(self.prefs_window.res_popup.titleOfSelectedItem(), "1200 dpi")

    def test_output_folder_drives_the_split_options(self) -> None:
        self.delegate.prefs["outputFolder"] = "/tmp/photosplit-test-out"
        self.assertEqual(
            self.delegate.prefs.as_split_options().output_dir,
            Path("/tmp/photosplit-test-out"),
        )


if __name__ == "__main__":
    unittest.main()

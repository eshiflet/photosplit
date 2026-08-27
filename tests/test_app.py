"""Checks on the app's window, its controls, and its preferences round-trip.

These build the real windows offscreen. They do not run the event loop, so no
window ever appears; what they verify is that every control the app depends on
exists, is wired to an action, and stays readable in dark mode.
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from AppKit import (
    NSAppearance,
    NSAppearanceNameAqua,
    NSAppearanceNameDarkAqua,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSButton,
    NSColor,
    NSForegroundColorAttributeName,
    NSPopUpButton,
)
from Foundation import NSBundle, NSUserDefaults

from photosplit.app import AppDelegate, PreferencesWindow
from photosplit.prefs import (
    FORMAT_LABELS,
    FORMATS,
    QUALITIES,
    QUALITY_LABELS,
    RESOLUTIONS,
)
from photosplit.scanner import run_loop_until
from tests.make_scan import SEPARATED, make

from photosplit import prefs as prefs_module

NSApplication.sharedApplication().setActivationPolicy_(
    NSApplicationActivationPolicyAccessory
)

_REAL_SUITE = prefs_module.SUITE
_TEST_SUITE = f"com.photosplit.app.tests.{uuid.uuid4().hex}"


def setUpModule() -> None:
    """Never let a test run rewrite the settings of the installed app."""
    prefs_module.SUITE = _TEST_SUITE


def tearDownModule() -> None:
    prefs_module.SUITE = _REAL_SUITE
    NSUserDefaults.standardUserDefaults().removePersistentDomainForName_(_TEST_SUITE)


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


class AppTestCase(unittest.TestCase):
    """Every test starts from stock preferences, whatever ran before it."""

    def setUp(self) -> None:
        NSUserDefaults.standardUserDefaults().removePersistentDomainForName_(_TEST_SUITE)
        # Nothing in here may open a Finder window. Several of these run a
        # whole split, and revealWhenDone defaults to on, so every run of the
        # suite used to leave another handful of windows open on the machine
        # that ran it -- dozens of them after an afternoon's work.
        prefs_module.Prefs(_TEST_SUITE)["revealWhenDone"] = False


class WindowTest(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.delegate = build_delegate()

    def test_window_exists_with_a_scan_button_bound_to_an_action(self) -> None:
        self.assertEqual(self.delegate.window.title(), "Photosplit")
        button = self.delegate.scan_button
        self.assertIsInstance(button, NSButton)
        self.assertEqual(button.title(), "Run Scan")

        # The rounded bezel silently caps its cell at 32 pt, so a 60 pt frame
        # drew a thin capsule adrift in it with the title crammed against the
        # edge. Whatever the style, the button has to fill its own frame and
        # leave room around the words.
        size = button.frame().size
        self.assertGreaterEqual(size.height, button.cell().cellSize().height)
        title = button.attributedTitle().size()
        self.assertGreater(size.width, title.width + 16)
        self.assertGreater(size.height, title.height + 8)
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

    def test_logged_lines_carry_their_own_colour(self) -> None:
        # Setting the view's textColor is not enough: text appended through
        # mutableString() arrives with no attributes and draws black whatever
        # the property says. Check what is actually in the storage, since the
        # property test above passes happily while the window is unreadable.
        self.delegate._log("a line")
        storage = self.delegate.log_view.textStorage()
        self.assertGreater(storage.length(), 0)
        attributes = storage.attributesAtIndex_effectiveRange_(0, None)[0]
        colour = attributes.get(NSForegroundColorAttributeName)
        self.assertIsNotNone(colour, "logged text carries no colour of its own")

        back = self.delegate.log_view.backgroundColor()
        for appearance in (NSAppearanceNameAqua, NSAppearanceNameDarkAqua):
            self.assertGreater(
                abs(luminance(colour, appearance) - luminance(back, appearance)),
                0.4,
                f"logged text is unreadable in {appearance}",
            )

    def test_calibrate_button_exists_and_is_wired(self) -> None:
        window = PreferencesWindow.alloc().initWithPrefs_owner_(self.delegate.prefs, self.delegate)
        button = window.calibrate_button
        self.assertEqual(button.title(), "Calibrate…")
        self.assertEqual(button.action(), "calibrate:")
        self.assertIs(button.target(), self.delegate)
        self.assertTrue(self.delegate.respondsToSelector_("calibrate:"))
        self.assertTrue(button.toolTip())

    def test_confirming_names_the_action_not_continue(self) -> None:
        # A button is read on its own, and on its own "Continue" says nothing
        # about what is about to happen to the glass.
        seen = {}

        def fake(title, message, go):
            seen.update(title=title, message=message, go=go)
            return False

        original = self.delegate._confirm
        try:
            self.delegate._confirm = fake
            self.delegate.devices = [object()]
            self.delegate.calibrate_(None)
        finally:
            self.delegate._confirm = original
            self.delegate.devices = []
        self.assertEqual(seen.get("go"), "Run Calibration")
        self.assertNotIn("continue", seen.get("message", "").lower())

    def test_preferences_closes_so_the_log_is_visible(self) -> None:
        # The progress and the verdict are written to the main window's log,
        # which is no use behind the Preferences window.
        window = PreferencesWindow.alloc().initWithPrefs_owner_(self.delegate.prefs, self.delegate)
        self.delegate.prefs_window = window
        window.show()
        self.assertTrue(window.window.isVisible())

        self.delegate._close_preferences()
        self.assertFalse(window.window.isVisible())
        self.assertTrue(self.delegate.window.isVisible())

    def test_calibrating_without_a_scanner_does_nothing(self) -> None:
        # No scanner is attached in the tests; this must not raise or prompt.
        self.assertFalse(self.delegate.devices)
        self.delegate.calibrate_(None)
        self.assertFalse(self.delegate.busy)

    def test_log_appends_lines(self) -> None:
        self.delegate._log("first")
        self.delegate._log("second")
        self.assertIn("first\nsecond", str(self.delegate.log_view.string()))


class SplitPathTest(AppTestCase):
    """The work the Scan button kicks off, minus the scanner itself.

    Splitting runs on a background thread and reports back through the main
    queue, so this drives a real run loop rather than asserting on the calls.
    """

    def setUp(self) -> None:
        super().setUp()
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-app-"))
        self.scan = self.dir / "bench.png"
        make(self.scan, SEPARATED)
        self.delegate = build_delegate()
        self.delegate.prefs["outputFolder"] = str(self.dir / "out")

    def test_splitting_here_never_opens_a_finder_window(self) -> None:
        # The tests below run whole splits. With revealWhenDone left at its
        # default each one hands Finder a window that nobody closes, and they
        # pile up across runs on whichever Mac is running the suite.
        self.assertFalse(
            bool(self.delegate.prefs["revealWhenDone"]),
            "a test that reveals its output leaves Finder windows behind",
        )

    def test_dropped_scan_is_split_into_files_and_the_original_kept(self) -> None:
        self.delegate._run_split([self.scan], source="dropped", dpi=300)
        finished = run_loop_until(lambda: not self.delegate.busy, 60.0)

        self.assertTrue(finished, "split never finished")
        written = sorted((self.dir / "out").glob("bench-*.jpg"))
        self.assertEqual(len(written), 4)
        self.assertTrue(self.scan.exists(), "a dropped file must not be deleted")
        self.assertIn("4 photo(s)", self.delegate.status.stringValue())

    def test_the_log_names_every_file_it_wrote(self) -> None:
        self.delegate._run_split([self.scan], source="dropped", dpi=300)
        run_loop_until(lambda: not self.delegate.busy, 60.0)
        log = str(self.delegate.log_view.string())
        for index in range(1, 5):
            self.assertIn(f"bench-{index:02d}.jpg", log)

    def test_a_scanned_file_is_discarded_once_split(self) -> None:
        self.delegate.prefs["keepFullScan"] = False
        self.delegate._run_split([self.scan], source="scanned", dpi=300)
        run_loop_until(lambda: not self.delegate.busy, 60.0)
        self.assertFalse(self.scan.exists(), "the temporary full scan should be gone")
        self.assertEqual(len(list((self.dir / "out").glob("bench-*.jpg"))), 4)

    def test_keeping_the_full_scan_leaves_it_alone(self) -> None:
        self.delegate.prefs["keepFullScan"] = True
        self.delegate._run_split([self.scan], source="scanned", dpi=300)
        run_loop_until(lambda: not self.delegate.busy, 60.0)
        self.assertTrue(self.scan.exists())


def every_button(view) -> list:
    found = []
    for sub in view.subviews():
        if isinstance(sub, NSButton):
            found.append(sub)
        found += every_button(sub)
    return found


class ControlsTest(AppTestCase):
    """Press everything the user can press."""

    def setUp(self) -> None:
        super().setUp()
        self.delegate = build_delegate()
        self.delegate.prefs_window = None

    def test_every_button_is_wired_to_something_that_answers(self) -> None:
        self.delegate.showPreferences_(None)
        windows = [self.delegate.window, self.delegate.prefs_window.window]
        buttons = [b for w in windows for b in every_button(w.contentView())]
        self.assertGreaterEqual(len(buttons), 8)
        for button in buttons:
            action = button.action()
            self.assertIsNotNone(action, "a button with no action")
            target = button.target()
            self.assertIsNotNone(target, f"{button.title()} has no target")
            self.assertTrue(
                target.respondsToSelector_(action),
                f"{button.title()} points at {action}, which its target does not implement",
            )

    def test_choosing_a_scanner_remembers_it_immediately(self) -> None:
        self.delegate._devices_changed(
            [FakeDevice("EPSON Perfection V500"), FakeDevice("HP Color LaserJet")]
        )
        self.delegate.device_popup.selectItemAtIndex_(1)
        self.delegate.deviceChanged_(None)
        self.assertEqual(str(self.delegate.prefs["scannerName"]), "HP Color LaserJet")

    def test_windows_are_not_freed_when_closed(self) -> None:
        # AppKit releases a window like these on close by default, leaving the
        # Python reference dangling; the next button press then crashes inside
        # object_getClass, with no Python traceback to show for it.
        self.delegate.showPreferences_(None)
        for window in (self.delegate.window, self.delegate.prefs_window.window):
            self.assertFalse(window.isReleasedWhenClosed())

    def test_preferences_survives_close_and_reopen(self) -> None:
        self.delegate.showPreferences_(None)
        window = self.delegate.prefs_window.window
        self.assertFalse(window.isReleasedWhenClosed(), "reopening would touch freed memory")
        window.close()
        self.delegate.showPreferences_(None)
        self.assertTrue(self.delegate.prefs_window.window.isVisible())
        self.delegate.prefs_window.window.close()

    def test_refresh_replaces_the_browser_rather_than_restarting_it(self) -> None:
        self.delegate._start_browsing()
        first = self.delegate.hub
        self.delegate.refresh_(None)
        self.assertIsNot(self.delegate.hub, first)
        self.assertEqual(self.delegate.devices, [])
        self.delegate.hub.stop()

    def test_refresh_is_ignored_mid_scan(self) -> None:
        self.delegate._start_browsing()
        hub = self.delegate.hub
        self.delegate._set_busy(True, "Scanning…")
        self.delegate.refresh_(None)
        self.assertIs(self.delegate.hub, hub, "must not drop the browser during a scan")
        self.delegate._set_busy(False, "")
        hub.stop()


class PreferencesStoreTest(AppTestCase):
    def test_a_suite_named_after_the_running_bundle_still_works(self) -> None:
        """Inside Photosplit.app the suite name and the bundle id are the same.

        macOS refuses that pairing and hands back nil, which crashed the app on
        launch while every script-run test passed.
        """
        identifier = NSBundle.mainBundle().bundleIdentifier()
        self.assertTrue(identifier, "no bundle identifier to test against")
        prefs = prefs_module.Prefs(suite=identifier)
        self.assertIsNotNone(prefs._store)
        self.assertEqual(int(prefs["resolution"]), prefs_module.DEFAULTS["resolution"])


class PreferencesTest(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.delegate = build_delegate()
        self.prefs_window = PreferencesWindow.alloc().initWithPrefs_owner_(
            self.delegate.prefs, self.delegate
        )

    def test_every_control_is_offered(self) -> None:
        self.assertEqual(
            titles(self.prefs_window.res_popup), [f"{r} dpi" for r in RESOLUTIONS]
        )
        self.assertEqual(titles(self.prefs_window.fmt_popup), FORMAT_LABELS)
        self.assertEqual(titles(self.prefs_window.quality_popup), QUALITY_LABELS)

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

    def test_jpeg_quality_reaches_the_saved_files(self) -> None:
        window = self.prefs_window
        window.fmt_popup.selectItemAtIndex_(FORMATS.index("jpg"))
        window.quality_popup.selectItemAtIndex_(QUALITIES.index(100))
        window.changed_(None)
        self.assertEqual(self.delegate.prefs.as_split_options().quality, 100)

    def test_quality_is_disabled_for_the_lossless_formats(self) -> None:
        window = self.prefs_window
        window.fmt_popup.selectItemAtIndex_(FORMATS.index("png"))
        window.changed_(None)
        self.assertFalse(window.quality_popup.isEnabled())
        window.fmt_popup.selectItemAtIndex_(FORMATS.index("jpg"))
        window.changed_(None)
        self.assertTrue(window.quality_popup.isEnabled())

    def test_the_window_shows_the_current_settings(self) -> None:
        self.delegate.prefs["resolution"] = 600
        self.delegate.prefs["quality"] = 98
        self.delegate.prefs["format"] = "jpg"
        self.delegate._refresh_footer()
        shown = str(self.delegate.settings_label.stringValue())
        self.assertIn("600 dpi", shown)
        self.assertIn("98", shown)

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

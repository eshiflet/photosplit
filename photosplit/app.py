"""Photosplit.app — put photos on the glass, press Scan, get one file each.

The window is deliberately one button. Everything adjustable lives in
Preferences, so the repetitive job (scan, split, save, scan the next batch)
stays a single keystroke.
"""

from __future__ import annotations

import sys
import tempfile
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezelStyleRegularSquare,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSOpenPanel,
    NSPopUpButton,
    NSProgressIndicator,
    NSProgressIndicatorStyleBar,
    NSScrollView,
    NSSwitchButton,
    NSTabView,
    NSTabViewItem,
    NSTextField,
    NSTextView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSAttributedString, NSObject, NSOperationQueue, NSTimer

from . import __version__
from . import blank as blank_module
from .dust import MIN_DPI as DUST_MIN_DPI
from .dust import STRENGTHS as _DUST

DUST_STRENGTHS = list(_DUST)
from .prefs import (
    FORMAT_LABELS,
    FORMATS,
    MODE_ACTIONS,
    MODE_LABELS,
    BIT_DEPTHS,
    MODE_RESOLUTIONS,
    MODES,
    PRINT,
    QUALITIES,
    QUALITY_LABELS,
    RESOLUTIONS,
    Prefs,
)
from .scanner import FLATBED, ScannerHub, ScanSession, ScanSettings
from .split import SCAN_SUFFIXES, split_scan

SCAN_TITLE = "Run Scan"
SCANNING_TITLE = "Scanning…"
# Calibration is always taken at one resolution, whatever the user scans at:
# a speck count is only meaningful against the last one, and changing the
# sampling underneath it would make every comparison a lie.
CALIBRATION_DPI = 600
CALIBRATE_TITLE = "Run Calibration"
# A scan that has not finished by now is not slow, it is stuck. Measured: a
# 600 dpi film scan is 9 megapixels and takes under a minute, so the budget is
# generous several times over before anything is called off.
STALL_ADVICE_AFTER = 90.0
STALL_BUDGET_BASE = 120.0
STALL_SECONDS_PER_MPX = 15.0

WINDOW_STYLE = (
    NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
)


def on_main(function, *args) -> None:
    """Hop back to the main thread; AppKit tolerates nothing else."""
    NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: function(*args))


def label(text: str, frame, *, bold: bool = False, secondary: bool = False) -> NSTextField:
    field = NSTextField.labelWithString_(text)
    field.setFrame_(frame)
    if bold:
        field.setFont_(NSFont.boldSystemFontOfSize_(13))
    if secondary:
        field.setFont_(NSFont.systemFontOfSize_(11))
        field.setTextColor_(NSColor.secondaryLabelColor())
    return field


def checkbox(title: str, frame, target, action: str) -> NSButton:
    box = NSButton.alloc().initWithFrame_(frame)
    box.setButtonType_(NSSwitchButton)
    box.setTitle_(title)
    box.setTarget_(target)
    box.setAction_(action)
    return box


class AppDelegate(NSObject):
    # -- lifecycle ---------------------------------------------------------
    def init(self):
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.prefs = Prefs()
        self.hub = None
        self.session = None
        self.devices: list = []
        self.busy = False
        return self

    def applicationDidFinishLaunching_(self, notification) -> None:
        self._build_menu()
        self._build_window()
        self.prefs_window = None
        self.stall_timer = None
        self._scan_started = 0.0
        self._stall_advised = False
        self._start_browsing()
        self._log(f"Photosplit {__version__} — looking for a scanner…")
        self._log(f"Saving to {self.prefs.output_folder}")
        self._refresh_footer()

    def applicationShouldTerminateAfterLastWindowClosed_(self, app) -> bool:
        return True

    def application_openFiles_(self, app, paths) -> None:
        """Existing scans dragged onto the app get split with the same settings."""
        scans = [
            Path(p)
            for p in paths
            if Path(p).suffix.lower() in SCAN_SUFFIXES or Path(p).is_dir()
        ]
        if scans and not self.busy:
            self._run_split(scans, source="dropped")

    # -- window ------------------------------------------------------------
    @objc.python_method
    def _build_window(self) -> None:
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 520, 470), WINDOW_STYLE, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Photosplit")
        # A window made this way is released the moment it is closed, which
        # leaves the Python reference dangling and crashes the next button
        # press. This object outlives its window's visibility.
        self.window.setReleasedWhenClosed_(False)
        self.window.center()
        view = self.window.contentView()

        view.addSubview_(label("Scanner", NSMakeRect(24, 424, 80, 18), bold=True))
        self.device_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(90, 419, 320, 26), False
        )
        self.device_popup.addItemWithTitle_("Looking for scanners…")
        self.device_popup.setEnabled_(False)
        self.device_popup.setTarget_(self)
        self.device_popup.setAction_("deviceChanged:")
        view.addSubview_(self.device_popup)

        refresh = NSButton.alloc().initWithFrame_(NSMakeRect(416, 418, 80, 28))
        refresh.setTitle_("Refresh")
        refresh.setBezelStyle_(NSBezelStyleRounded)
        refresh.setTarget_(self)
        refresh.setAction_("refresh:")
        view.addSubview_(refresh)

        view.addSubview_(label("Scanning", NSMakeRect(24, 392, 80, 18), bold=True))
        self.mode_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(90, 387, 200, 26), False
        )
        self.mode_popup.addItemsWithTitles_([MODE_LABELS[m] for m in MODES])
        self.mode_popup.setTarget_(self)
        self.mode_popup.setAction_("modeChanged:")
        view.addSubview_(self.mode_popup)

        self.scan_button = NSButton.alloc().initWithFrame_(NSMakeRect(24, 300, 472, 60))
        self.scan_button.setTitle_(MODE_ACTIONS[self.prefs.mode])
        # A rounded bezel will not grow: its cell is 32 pt tall whatever the
        # frame says, so this button drew a thin capsule floating inside 60 pt
        # of nothing while the 22 pt title crowded the edge of it. The square
        # bezel is the one that takes an arbitrary height.
        self.scan_button.setBezelStyle_(NSBezelStyleRegularSquare)
        self.scan_button.setFont_(NSFont.systemFontOfSize_(22))
        self.scan_button.setKeyEquivalent_("\r")
        self.scan_button.setTarget_(self)
        self.scan_button.setAction_("scan:")
        self.scan_button.setEnabled_(False)
        view.addSubview_(self.scan_button)

        self.progress = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(24, 322, 472, 16)
        )
        self.progress.setStyle_(NSProgressIndicatorStyleBar)
        self.progress.setIndeterminate_(True)
        self.progress.setHidden_(True)
        view.addSubview_(self.progress)

        self.status = label("", NSMakeRect(24, 298, 472, 18), secondary=True)
        view.addSubview_(self.status)

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(24, 96, 472, 194))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(2)
        self.log_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 472, 194))
        self.log_view.setEditable_(False)
        self.log_view.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11, 0))
        # Without these the log is black-on-black the moment the Mac is in dark mode.
        self.log_view.setDrawsBackground_(True)
        self.log_view.setBackgroundColor_(NSColor.textBackgroundColor())
        self.log_view.setTextColor_(NSColor.textColor())
        scroll.setDocumentView_(self.log_view)
        view.addSubview_(scroll)

        self.folder_label = label("", NSMakeRect(24, 68, 472, 18), secondary=True)
        view.addSubview_(self.folder_label)
        self.settings_label = label("", NSMakeRect(24, 48, 472, 18), secondary=True)
        view.addSubview_(self.settings_label)
        self._refresh_footer()

        settings_button = NSButton.alloc().initWithFrame_(NSMakeRect(24, 12, 140, 28))
        settings_button.setTitle_("Preferences…")
        settings_button.setBezelStyle_(NSBezelStyleRounded)
        settings_button.setTarget_(self)
        settings_button.setAction_("showPreferences:")
        view.addSubview_(settings_button)

        reveal = NSButton.alloc().initWithFrame_(NSMakeRect(360, 12, 136, 28))
        reveal.setTitle_("Open Folder")
        reveal.setBezelStyle_(NSBezelStyleRounded)
        reveal.setTarget_(self)
        reveal.setAction_("reveal:")
        view.addSubview_(reveal)

        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def _build_menu(self) -> None:
        menubar = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        menubar.addItem_(app_item)
        NSApp.setMainMenu_(menubar)

        app_menu = NSMenu.alloc().init()
        app_menu.addItemWithTitle_action_keyEquivalent_(
            "Preferences…", "showPreferences:", ","
        ).setTarget_(self)
        app_menu.addItem_(NSMenuItem.separatorItem())
        app_menu.addItemWithTitle_action_keyEquivalent_("Quit Photosplit", "terminate:", "q")
        app_item.setSubmenu_(app_menu)

    # -- scanner list ------------------------------------------------------
    @objc.python_method
    def _devices_changed(self, devices) -> None:
        self.devices = list(devices)
        self.device_popup.removeAllItems()
        if not self.devices:
            self.device_popup.addItemWithTitle_("No scanner found")
            self.device_popup.setEnabled_(False)
            self.scan_button.setEnabled_(False)
            self._log("No scanner found. Check that it is plugged in and switched on.")
            return

        self.device_popup.addItemsWithTitles_([d.name() for d in self.devices])
        self.device_popup.setEnabled_(True)
        self.scan_button.setEnabled_(not self.busy)

        remembered = str(self.prefs["scannerName"])
        names = [d.name() for d in self.devices]
        if remembered in names:
            self.device_popup.selectItemAtIndex_(names.index(remembered))
        self._log(f"Ready: {self.device_popup.titleOfSelectedItem()}")

    @objc.python_method
    def _start_browsing(self) -> None:
        """Begin device discovery, replacing any previous browser.

        A browser that has been stopped is not restartable, and the device
        objects it produced belong to it, so both are dropped together.
        """
        if self.hub is not None:
            self.hub.stop()
        self.devices = []
        self.hub = ScannerHub.alloc().initWithCallback_(
            lambda devices: on_main(self._devices_changed, devices)
        )
        self.hub.start()

    def deviceChanged_(self, sender) -> None:
        """Remember the chosen scanner as soon as it is chosen."""
        index = self.device_popup.indexOfSelectedItem()
        if 0 <= index < len(self.devices):
            self.prefs["scannerName"] = self.devices[index].name()

    # -- noticing a scan that is not happening ------------------------------
    @objc.python_method
    def _watch_for_stall(self) -> None:
        self._scan_started = time.monotonic()
        self._stall_advised = False
        self.stall_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            5.0, self, "checkProgress:", None, True
        )

    @objc.python_method
    def _stop_watching(self) -> None:
        if getattr(self, "stall_timer", None) is not None:
            self.stall_timer.invalidate()
            self.stall_timer = None

    def checkProgress_(self, timer) -> None:
        if not self.busy or self.session is None:
            return self._stop_watching()
        waited = time.monotonic() - self._scan_started

        if waited > STALL_ADVICE_AFTER and not self._stall_advised:
            self._stall_advised = True
            for line in self._stall_advice():
                self._log(line)

        budget = STALL_BUDGET_BASE + STALL_SECONDS_PER_MPX * max(
            self.session.expected_megapixels(), 1.0
        )
        if waited > budget:
            self._stop_watching()
            # Close the session on the way out. Walking away from it is what
            # leaves the scanner blinking and refusing the next scan.
            self.session.give_up(
                f"No image after {waited / 60:.0f} minutes. The scanner never started."
            )

    @objc.python_method
    def _stall_advice(self) -> list[str]:
        """What to try, for the scanner and mode this actually is."""
        lines = ["  Still waiting. The scanner has not sent anything yet."]
        if self.prefs.unit != FLATBED:
            lines.append(
                "  On an Epson, film scanning needs the white document mat taken"
                " out of the lid — it covers the lamp that shines through the film."
            )
            lines.append("  Take the mat out, then switch the scanner off and on again.")
        else:
            lines.append(
                "  Check the lid is closed and the scanner's light is steady rather"
                " than blinking. If it blinks, switch it off and on again."
            )
        return lines

    def modeChanged_(self, sender) -> None:
        """Remember what is being scanned, and say so on the button."""
        index = self.mode_popup.indexOfSelectedItem()
        if 0 <= index < len(MODES):
            self.prefs.mode = MODES[index]
        self._set_busy(self.busy, "")
        self._refresh_footer()
        if self.prefs_window is not None:
            self.prefs_window.show_for_mode()

    def refresh_(self, sender) -> None:
        if self.busy:
            return
        self._start_browsing()
        self._log("Looking for scanners again…")

    # -- the one button ----------------------------------------------------
    def scan_(self, sender) -> None:
        if self.busy or not self.devices:
            return
        device = self.devices[max(0, self.device_popup.indexOfSelectedItem())]
        self.prefs["scannerName"] = device.name()

        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        settings = ScanSettings(
            resolution=int(self.prefs.get("resolution")),
            colour=bool(self.prefs["colour"]),
            downloads_dir=self._scan_destination(),
            document_name=stamp,
            unit=self.prefs.unit,
            bit_depth=int(self.prefs.get("bitDepth")),
        )
        self._set_busy(True, "Waking the scanner…")
        self._log(f"--- {stamp} ---")
        self.session = ScanSession.alloc().initWithDevice_settings_status_done_(
            device,
            settings,
            lambda text: on_main(self._status, text),
            lambda path, error: on_main(self._scan_finished, path, error),
        )
        self.session.start()
        self._watch_for_stall()

    # -- glass calibration -------------------------------------------------
    def calibrate_(self, sender) -> None:
        """Scan the empty bed and record what is on it."""
        if self.busy or not self.devices:
            return
        if not self._confirm(
            "Calibrate the glass",
            "Take everything off the glass and close the lid. Photosplit will "
            "scan the empty bed and record what it finds.",
            CALIBRATE_TITLE,
        ):
            return
        # The progress and the verdict are written to the main window's log, so
        # send the user there rather than leaving Preferences over the top of it.
        self._close_preferences()
        device = self.devices[max(0, self.device_popup.indexOfSelectedItem())]
        settings = ScanSettings(
            resolution=CALIBRATION_DPI,
            colour=True,
            downloads_dir=Path(tempfile.mkdtemp(prefix="photosplit-calibration-")),
            document_name="blank",
            unit=FLATBED,  # the glass is the glass, whatever mode the window is in
        )
        self._set_busy(True, "Scanning the empty bed…")
        self._log("--- calibrating the glass ---")
        self.session = ScanSession.alloc().initWithDevice_settings_status_done_(
            device,
            settings,
            lambda text: on_main(self._status, text),
            lambda path, error: on_main(self._calibration_finished, path, error),
        )
        self.session.start()
        self._watch_for_stall()

    @objc.python_method
    def _calibration_finished(self, path: Path | None, error: str | None) -> None:
        self._stop_watching()
        if error or path is None:
            self._set_busy(False, "")
            self._log(f"Calibration failed: {error}")
            self._alert("The calibration did not finish", error or "No file was produced.")
            return
        try:
            folder = blank_module.calibration_folder()
            previous = blank_module.load_calibration(folder)
            measured, specks = blank_module.measure(
                path, self.session.actual_resolution()
            )
            blank_module.save_calibration(folder, measured, specks, path)
        except Exception:
            self._set_busy(False, "")
            self._log(traceback.format_exc().strip())
            self._alert("The calibration did not finish", "The empty bed could not be measured.")
            return
        finally:
            path.unlink(missing_ok=True)
            _remove_if_empty(path.parent)

        for line in blank_module.verdict(measured, previous):
            self._log(line)
        self._log(f"  dust map saved to {folder}")
        self._set_busy(False, "Calibrated")

    @objc.python_method
    def _scan_destination(self) -> Path:
        """Where the raw full-bed scan lands before it is split."""
        if bool(self.prefs["keepFullScan"]):
            return self.prefs.output_folder / "Full Scans"
        return Path(tempfile.mkdtemp(prefix="photosplit-"))

    @objc.python_method
    def _scan_finished(self, path: Path | None, error: str | None) -> None:
        self._stop_watching()
        if error or path is None:
            self._set_busy(False, "")
            self._log(f"Scan failed: {error}")
            self._alert("The scan did not finish", error or "The scanner produced no file.")
            return
        self._log(f"Scanned {path.name}")
        # Trust the scanner over the file's metadata: a TIFF that carries no
        # resolution tag would otherwise be measured as if it were 300 dpi.
        self._run_split([path], source="scanned", dpi=self.session.actual_resolution())

    # -- splitting ---------------------------------------------------------
    @objc.python_method
    def _run_split(self, scans: list[Path], source: str, dpi: float | None = None) -> None:
        self._set_busy(True, "Finding the photos…")
        options = self.prefs.as_split_options()
        if dpi is not None:
            options.dpi_override = float(dpi)
        # A dropped file is the user's own; only a scan we just made is ours to bin.
        discard = source == "scanned" and not bool(self.prefs["keepFullScan"])
        reveal = bool(self.prefs["revealWhenDone"])

        def work() -> None:
            written: list[Path] = []
            try:
                for scan in scans:
                    result = split_scan(scan, options)
                    written += result.written
                    on_main(self._report, result)
                    if discard:
                        scan.unlink(missing_ok=True)
                        _remove_if_empty(scan.parent)
            except Exception:
                on_main(self._log, traceback.format_exc().strip())
                on_main(self._alert, "Could not split the scan", traceback.format_exc(limit=1))
            finally:
                on_main(self._split_finished, written, reveal)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _report(self, result) -> None:
        if not result.count:
            self._log("  no photos found — is the lid closed?")
            return
        clipped = 0
        for index, (photo, target) in enumerate(zip(result.photos, result.written), start=1):
            w = photo.size[0] / result.dpi
            h = photo.size[1] / result.dpi
            note = ""
            if photo.clipped:
                clipped += 1
                note = "   << reaches the edge of the scan area"
            self._log(f"  {index:2d}. {w:4.1f} x {h:4.1f} in   {target.name}{note}")
        if clipped:
            self._log(
                f"  {clipped} photo(s) reach the edge of the scan area and may be"
                " incomplete. The scannable area is often smaller than the glass:"
                " move them inside the markers and scan again."
            )

    @objc.python_method
    def _split_finished(self, written: list[Path], reveal: bool) -> None:
        self._set_busy(False, f"{len(written)} photo(s) saved")
        self._log(f"Saved {len(written)} photo(s) to {self.prefs.output_folder}")
        if written and reveal:
            NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
                [_url(written[0])]
            )

    # -- small helpers -----------------------------------------------------
    @objc.python_method
    def _set_busy(self, busy: bool, message: str) -> None:
        self.busy = busy
        self.scan_button.setEnabled_(not busy and bool(self.devices))
        self.scan_button.setTitle_(
            SCANNING_TITLE if busy else MODE_ACTIONS[self.prefs.mode]
        )
        self.progress.setHidden_(not busy)
        if busy:
            self.progress.startAnimation_(None)
        else:
            self.progress.stopAnimation_(None)
        self._status(message)

    @objc.python_method
    def _status(self, text: str) -> None:
        self.status.setStringValue_(text)

    @objc.python_method
    def _log(self, text: str) -> None:
        storage = self.log_view.textStorage()
        # Appending through mutableString() puts characters in with no
        # attributes at all, which draws them in the default black however the
        # view's textColor is set -- black on black the moment the Mac is in
        # dark mode. The colour has to ride on the text itself. textColor()
        # stays dynamic inside the attributed string, so it still follows the
        # appearance if it changes while the window is open.
        line = NSAttributedString.alloc().initWithString_attributes_(
            text + "\n",
            {
                NSForegroundColorAttributeName: NSColor.textColor(),
                NSFontAttributeName: self.log_view.font(),
            },
        )
        storage.appendAttributedString_(line)
        self.log_view.scrollRangeToVisible_((storage.length(), 0))

    @objc.python_method
    def _refresh_footer(self) -> None:
        """Keep the current settings visible; they change what a scan costs."""
        shown = str(self.prefs.output_folder).replace(str(Path.home()), "~")
        self.folder_label.setStringValue_(f"Saving to {shown}")

        # Per mode, not the flat keys: those stopped being what a scan uses the
        # moment the modes arrived, so reading them showed a number that
        # nothing acted on and did not change when the mode did.
        fmt = str(self.prefs.get("format"))
        parts = [
            MODE_LABELS[self.prefs.mode],
            f"{int(self.prefs.get('resolution'))} dpi",
            f"{int(self.prefs.get('bitDepth'))}-bit",
            "colour" if self.prefs["colour"] else "greyscale",
            f"JPEG quality {int(self.prefs['quality'])}" if fmt == "jpg" else f"{fmt.upper()}, lossless",
        ]
        self.settings_label.setStringValue_(" · ".join(parts))

    # Kept for the preferences window, which calls back when the folder changes.
    @objc.python_method
    def _refresh_folder_label(self) -> None:
        self._refresh_footer()

    @objc.python_method
    def _alert(self, title: str, message: str) -> None:
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.runModal()

    @objc.python_method
    def _confirm(self, title: str, message: str, go: str) -> bool:
        """Ask before something that needs the glass in a particular state.

        The affirming button is named for the thing it starts, never "Continue":
        the button is read on its own, and on its own "Continue" says nothing.
        """
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_(go)
        alert.addButtonWithTitle_("Cancel")
        return int(alert.runModal()) == NSAlertFirstButtonReturn

    def reveal_(self, sender) -> None:
        folder = self.prefs.output_folder
        folder.mkdir(parents=True, exist_ok=True)
        NSWorkspace.sharedWorkspace().openURL_(_url(folder))

    @objc.python_method
    def _close_preferences(self) -> None:
        if self.prefs_window is not None:
            self.prefs_window.close()
        self.window.makeKeyAndOrderFront_(None)

    def showPreferences_(self, sender) -> None:
        if self.prefs_window is None:
            self.prefs_window = PreferencesWindow.alloc().initWithPrefs_owner_(self.prefs, self)
        self.prefs_window.show()


def _remove_if_empty(folder: Path) -> None:
    """Tidy away the throwaway folder a discarded scan was written into."""
    try:
        folder.rmdir()
    except OSError:
        pass


def _url(path: Path):
    from Foundation import NSURL

    return NSURL.fileURLWithPath_(str(path))


class PreferencesWindow(NSObject):
    """Everything adjustable, so the main window can stay one button."""

    def initWithPrefs_owner_(self, prefs: Prefs, owner):
        self = objc.super(PreferencesWindow, self).init()
        if self is None:
            return None
        self.prefs = prefs
        self.owner = owner
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 480, 420), WINDOW_STYLE, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Photosplit Preferences")
        self.window.setReleasedWhenClosed_(False)
        self.window.center()

        # Two pages rather than one long window. Making a scan and correcting
        # one afterwards are different jobs, done at different times, and the
        # second is only going to grow.
        tabs = NSTabView.alloc().initWithFrame_(NSMakeRect(8, 8, 464, 404))
        self.window.contentView().addSubview_(tabs)
        scanning = self._page(tabs, "Scanning")
        after = self._page(tabs, "Post-Processing")

        scanning.addSubview_(label("Save photos to", NSMakeRect(24, 344, 200, 18), bold=True))
        self.folder_field = label("", NSMakeRect(24, 322, 310, 18), secondary=True)
        scanning.addSubview_(self.folder_field)
        choose = NSButton.alloc().initWithFrame_(NSMakeRect(342, 314, 90, 28))
        choose.setTitle_("Choose…")
        choose.setBezelStyle_(NSBezelStyleRounded)
        choose.setTarget_(self)
        choose.setAction_("chooseFolder:")
        scanning.addSubview_(choose)

        self.quality_heading = label("Scan quality", NSMakeRect(24, 280, 300, 18), bold=True)
        scanning.addSubview_(self.quality_heading)
        scanning.addSubview_(label("Resolution", NSMakeRect(24, 252, 90, 18)))
        self.res_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(120, 247, 120, 26), False
        )
        self.res_popup.addItemsWithTitles_([f"{r} dpi" for r in RESOLUTIONS])
        self.res_popup.setTarget_(self)
        self.res_popup.setAction_("changed:")
        scanning.addSubview_(self.res_popup)

        scanning.addSubview_(label("Save as", NSMakeRect(252, 252, 60, 18)))
        self.fmt_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(312, 247, 120, 26), False
        )
        self.fmt_popup.addItemsWithTitles_(FORMAT_LABELS)
        self.fmt_popup.setTarget_(self)
        self.fmt_popup.setAction_("changed:")
        scanning.addSubview_(self.fmt_popup)

        scanning.addSubview_(label("JPEG quality", NSMakeRect(24, 216, 90, 18)))
        self.quality_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(120, 211, 120, 26), False
        )
        self.quality_popup.addItemsWithTitles_(QUALITY_LABELS)
        self.quality_popup.setTarget_(self)
        self.quality_popup.setAction_("changed:")
        scanning.addSubview_(self.quality_popup)

        scanning.addSubview_(label("Depth", NSMakeRect(252, 216, 60, 18)))
        self.depth_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(312, 211, 120, 26), False
        )
        self.depth_popup.addItemsWithTitles_([f"{d}-bit" for d in BIT_DEPTHS])
        self.depth_popup.setTarget_(self)
        self.depth_popup.setAction_("changed:")
        self.depth_popup.setToolTip_(
            "16-bit keeps shadow detail through the inversion a negative needs."
        )
        scanning.addSubview_(self.depth_popup)

        self.colour_box = checkbox(
            "Scan in colour", NSMakeRect(24, 180, 200, 20), self, "changed:"
        )
        scanning.addSubview_(self.colour_box)

        self.calibrate_button = NSButton.alloc().initWithFrame_(NSMakeRect(306, 174, 126, 28))
        self.calibrate_button.setTitle_("Calibrate…")  # … because it asks first
        self.calibrate_button.setBezelStyle_(NSBezelStyleRounded)
        self.calibrate_button.setTarget_(owner)
        self.calibrate_button.setAction_("calibrate:")
        self.calibrate_button.setToolTip_(
            "Scan the empty bed and record the dust on it. Run this after cleaning the glass."
        )
        scanning.addSubview_(self.calibrate_button)

        scanning.addSubview_(label("Cropping", NSMakeRect(24, 144, 200, 18), bold=True))
        scanning.addSubview_(label("Ignore anything smaller than", NSMakeRect(24, 116, 190, 18)))
        self.min_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(220, 111, 120, 26), False
        )
        self.min_popup.addItemsWithTitles_(['0.5"', '1"', '1.5"', '2"'])
        self.min_popup.setTarget_(self)
        self.min_popup.setAction_("changed:")
        scanning.addSubview_(self.min_popup)

        self.deskew_box = checkbox(
            "Straighten crooked photos", NSMakeRect(24, 84, 300, 20), self, "changed:"
        )
        self.trim_box = checkbox(
            "Trim leftover scanner background", NSMakeRect(24, 60, 300, 20), self, "changed:"
        )
        self.keep_box = checkbox(
            "Keep the full scan as well", NSMakeRect(24, 36, 300, 20), self, "changed:"
        )
        self.preview_box = checkbox(
            "Save a marked-up preview of each scan", NSMakeRect(24, 12, 340, 20), self, "changed:"
        )
        for box in (self.deskew_box, self.trim_box, self.keep_box, self.preview_box):
            scanning.addSubview_(box)

        # -- the second page ------------------------------------------------
        self.correction_heading = label(
            "Correction", NSMakeRect(24, 348, 400, 18), bold=True
        )
        after.addSubview_(self.correction_heading)

        self.invert_box = checkbox(
            "Negatives — turn them into positives",
            NSMakeRect(24, 320, 340, 20), self, "changed:",
        )
        after.addSubview_(self.invert_box)

        self.dust_box = checkbox(
            "Remove dust specks", NSMakeRect(24, 294, 200, 20), self, "changed:"
        )
        after.addSubview_(self.dust_box)
        self.dust_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(228, 289, 120, 26), False
        )
        self.dust_popup.addItemsWithTitles_([s.capitalize() for s in DUST_STRENGTHS])
        self.dust_popup.setTarget_(self)
        self.dust_popup.setAction_("changed:")
        after.addSubview_(self.dust_popup)
        self.dust_preview_box = checkbox(
            "Ring them instead of removing them, to check first",
            NSMakeRect(44, 266, 380, 20), self, "changed:",
        )
        after.addSubview_(self.dust_preview_box)
        self.dust_note = label("", NSMakeRect(24, 244, 408, 18), secondary=True)
        after.addSubview_(self.dust_note)

        after.addSubview_(label("Metadata", NSMakeRect(24, 206, 200, 18), bold=True))
        self.note_field = NSTextField.alloc().initWithFrame_(NSMakeRect(24, 176, 408, 24))
        self.note_field.setPlaceholderString_(
            "Film, exposure, what the picture is of — written into every file"
        )
        self.note_field.setTarget_(self)
        self.note_field.setAction_("changed:")
        after.addSubview_(self.note_field)

        after.addSubview_(label("Finishing", NSMakeRect(24, 138, 200, 18), bold=True))
        self.reveal_box = checkbox(
            "Open the folder when a scan finishes", NSMakeRect(24, 110, 340, 20), self, "changed:"
        )
        after.addSubview_(self.reveal_box)

        after.addSubview_(
            label(
                "These apply to the selected mode, and are done to the saved scan"
                " rather than to the scanner.",
                NSMakeRect(24, 12, 410, 34), secondary=True,
            )
        )

        self._load()
        return self

    @objc.python_method
    def _page(self, tabs, title: str):
        """One tab, and the view its controls go on."""
        item = NSTabViewItem.alloc().initWithIdentifier_(title)
        item.setLabel_(title)
        tabs.addTabViewItem_(item)
        return item.view()

    @objc.python_method
    def show(self) -> None:
        self._load()
        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def show_for_mode(self) -> None:
        """Repopulate for a mode chosen in the main window while this is open."""
        self._load()

    @objc.python_method
    def close(self) -> None:
        self.window.orderOut_(None)

    @objc.python_method
    def _load(self) -> None:
        prefs = self.prefs
        home = str(Path.home())
        self.folder_field.setStringValue_(str(prefs.output_folder).replace(home, "~"))
        # The resolutions worth offering depend on what is being scanned, so
        # the list is rebuilt whenever the mode changes rather than fixed.
        mode = prefs.mode
        self.quality_heading.setStringValue_(f"Scan quality — {MODE_LABELS[mode]}")
        choices = MODE_RESOLUTIONS[mode]
        self.res_popup.removeAllItems()
        self.res_popup.addItemsWithTitles_([f"{r} dpi" for r in choices])
        resolution = int(prefs.get("resolution"))
        if resolution in choices:
            self.res_popup.selectItemAtIndex_(choices.index(resolution))
        depth = int(prefs.get("bitDepth"))
        if depth in BIT_DEPTHS:
            self.depth_popup.selectItemAtIndex_(BIT_DEPTHS.index(depth))
        fmt = str(prefs.get("format"))
        if fmt in FORMATS:
            self.fmt_popup.selectItemAtIndex_(FORMATS.index(fmt))
        quality = int(prefs["quality"])
        self.quality_popup.selectItemAtIndex_(
            min(range(len(QUALITIES)), key=lambda i: abs(QUALITIES[i] - quality))
        )
        # Quality is a JPEG idea; PNG and TIFF are lossless either way.
        self.quality_popup.setEnabled_(fmt == "jpg")
        # 16-bit has nowhere to go in a JPEG.
        self.depth_popup.setEnabled_(fmt != "jpg")
        sizes = [0.5, 1.0, 1.5, 2.0]
        size = float(prefs.get("minSize"))
        self.min_popup.selectItemAtIndex_(
            min(range(len(sizes)), key=lambda i: abs(sizes[i] - size))
        )
        self.colour_box.setState_(1 if prefs["colour"] else 0)
        self.invert_box.setState_(1 if prefs.get("invert") else 0)
        # Dust and grain are only separable above a certain sampling, so the
        # resolution decides whether this can be offered at all.
        usable = prefs.dust_available()
        self.dust_box.setState_(1 if (prefs.get("dust") and usable) else 0)
        self.dust_box.setEnabled_(usable)
        strength = str(prefs.get("dustStrength"))
        if strength in DUST_STRENGTHS:
            self.dust_popup.selectItemAtIndex_(DUST_STRENGTHS.index(strength))
        self.dust_popup.setEnabled_(usable and bool(self.dust_box.state()))
        self.dust_preview_box.setState_(1 if prefs.get("dustPreview") else 0)
        self.dust_preview_box.setEnabled_(usable and bool(self.dust_box.state()))
        self.correction_heading.setStringValue_(f"Correction — {MODE_LABELS[prefs.mode]}")
        self.dust_note.setStringValue_(
            ""
            if usable
            else f"Dust removal needs {DUST_MIN_DPI} dpi or better: below that a"
            " speck cannot be told from film grain."
        )
        # Slide film in uncut strips is not a negative, and a print never is.
        self.invert_box.setEnabled_(prefs.mode != PRINT)
        self.deskew_box.setState_(1 if prefs["deskew"] else 0)
        self.trim_box.setState_(1 if prefs["trim"] else 0)
        self.keep_box.setState_(1 if prefs["keepFullScan"] else 0)
        self.preview_box.setState_(1 if prefs["writePreview"] else 0)
        self.reveal_box.setState_(1 if prefs["revealWhenDone"] else 0)
        self.note_field.setStringValue_(str(prefs.get("note")))

    def changed_(self, sender) -> None:
        prefs = self.prefs
        choices = MODE_RESOLUTIONS[prefs.mode]
        index = self.res_popup.indexOfSelectedItem()
        if 0 <= index < len(choices):
            prefs.set("resolution", choices[index])
        prefs.set("bitDepth", BIT_DEPTHS[self.depth_popup.indexOfSelectedItem()])
        prefs.set("format", FORMATS[self.fmt_popup.indexOfSelectedItem()])
        prefs["quality"] = QUALITIES[self.quality_popup.indexOfSelectedItem()]
        prefs.set("minSize", [0.5, 1.0, 1.5, 2.0][self.min_popup.indexOfSelectedItem()])
        prefs["colour"] = bool(self.colour_box.state())
        prefs.set("invert", bool(self.invert_box.state()))
        prefs.set("dust", bool(self.dust_box.state()))
        index = self.dust_popup.indexOfSelectedItem()
        if 0 <= index < len(DUST_STRENGTHS):
            prefs.set("dustStrength", DUST_STRENGTHS[index])
        prefs.set("dustPreview", bool(self.dust_preview_box.state()))
        prefs["deskew"] = bool(self.deskew_box.state())
        prefs["trim"] = bool(self.trim_box.state())
        prefs["keepFullScan"] = bool(self.keep_box.state())
        prefs["writePreview"] = bool(self.preview_box.state())
        prefs["revealWhenDone"] = bool(self.reveal_box.state())
        prefs.set("note", str(self.note_field.stringValue()))
        self.quality_popup.setEnabled_(str(prefs.get("format")) == "jpg")
        self.owner._refresh_footer()

    def chooseFolder_(self, sender) -> None:
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setCanCreateDirectories_(True)
        panel.setPrompt_("Choose")
        panel.setDirectoryURL_(_url(self.prefs.output_folder))
        if panel.runModal() == 1 and panel.URLs():
            self.prefs["outputFolder"] = str(Path(panel.URLs()[0].path()))
            self._load()
            self.owner._refresh_folder_label()


def self_test() -> int:
    """Build the whole interface once and exit.

    Run from inside the built bundle, this catches the failures that only
    happen there — a bundle identifier clashing with the preferences suite
    being the one that shipped broken.
    """
    NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    delegate._build_menu()
    delegate._build_window()
    delegate.prefs_window = None
    PreferencesWindow.alloc().initWithPrefs_owner_(delegate.prefs, delegate)
    identifier = __import__("Foundation").NSBundle.mainBundle().bundleIdentifier()
    print(f"self-test ok — bundle {identifier}, saving to {delegate.prefs.output_folder}")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.activateIgnoringOtherApps_(True)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

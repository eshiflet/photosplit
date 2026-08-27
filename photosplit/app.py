"""Photosplit.app — put photos on the glass, press Scan, get one file each.

The window is deliberately one button. Everything adjustable lives in
Preferences, so the repetitive job (scan, split, save, scan the next batch)
stays a single keystroke.
"""

from __future__ import annotations

import sys
import tempfile
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
    NSTextField,
    NSTextView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSAttributedString, NSObject, NSOperationQueue

from . import __version__
from . import blank as blank_module
from .prefs import FORMAT_LABELS, FORMATS, QUALITIES, QUALITY_LABELS, RESOLUTIONS, Prefs
from .scanner import ScannerHub, ScanSession, ScanSettings
from .split import SCAN_SUFFIXES, split_scan

SCAN_TITLE = "Run Scan"
SCANNING_TITLE = "Scanning…"
# Calibration is always taken at one resolution, whatever the user scans at:
# a speck count is only meaningful against the last one, and changing the
# sampling underneath it would make every comparison a lie.
CALIBRATION_DPI = 600
CALIBRATE_TITLE = "Run Calibration"

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

        self.scan_button = NSButton.alloc().initWithFrame_(NSMakeRect(24, 344, 472, 60))
        self.scan_button.setTitle_(SCAN_TITLE)
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
            resolution=int(self.prefs["resolution"]),
            colour=bool(self.prefs["colour"]),
            downloads_dir=self._scan_destination(),
            document_name=stamp,
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

    @objc.python_method
    def _calibration_finished(self, path: Path | None, error: str | None) -> None:
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
        self.scan_button.setTitle_(SCANNING_TITLE if busy else SCAN_TITLE)
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

        fmt = str(self.prefs["format"])
        parts = [
            f"{int(self.prefs['resolution'])} dpi",
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
        view = self.window.contentView()

        view.addSubview_(label("Save photos to", NSMakeRect(24, 376, 200, 18), bold=True))
        self.folder_field = label("", NSMakeRect(24, 354, 330, 18), secondary=True)
        view.addSubview_(self.folder_field)
        choose = NSButton.alloc().initWithFrame_(NSMakeRect(366, 346, 90, 28))
        choose.setTitle_("Choose…")
        choose.setBezelStyle_(NSBezelStyleRounded)
        choose.setTarget_(self)
        choose.setAction_("chooseFolder:")
        view.addSubview_(choose)

        view.addSubview_(label("Scan quality", NSMakeRect(24, 308, 200, 18), bold=True))
        view.addSubview_(label("Resolution", NSMakeRect(24, 280, 90, 18)))
        self.res_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(120, 275, 120, 26), False
        )
        self.res_popup.addItemsWithTitles_([f"{r} dpi" for r in RESOLUTIONS])
        self.res_popup.setTarget_(self)
        self.res_popup.setAction_("changed:")
        view.addSubview_(self.res_popup)

        view.addSubview_(label("Save as", NSMakeRect(252, 280, 60, 18)))
        self.fmt_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(312, 275, 144, 26), False
        )
        self.fmt_popup.addItemsWithTitles_(FORMAT_LABELS)
        self.fmt_popup.setTarget_(self)
        self.fmt_popup.setAction_("changed:")
        view.addSubview_(self.fmt_popup)

        view.addSubview_(label("JPEG quality", NSMakeRect(24, 244, 90, 18)))
        self.quality_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(120, 239, 200, 26), False
        )
        self.quality_popup.addItemsWithTitles_(QUALITY_LABELS)
        self.quality_popup.setTarget_(self)
        self.quality_popup.setAction_("changed:")
        view.addSubview_(self.quality_popup)

        self.colour_box = checkbox(
            "Scan in colour", NSMakeRect(24, 208, 200, 20), self, "changed:"
        )
        view.addSubview_(self.colour_box)

        self.calibrate_button = NSButton.alloc().initWithFrame_(
            NSMakeRect(330, 202, 126, 28)
        )
        self.calibrate_button.setTitle_("Calibrate…")  # … because it asks first
        self.calibrate_button.setBezelStyle_(NSBezelStyleRounded)
        self.calibrate_button.setTarget_(owner)
        self.calibrate_button.setAction_("calibrate:")
        self.calibrate_button.setToolTip_(
            "Scan the empty bed and record the dust on it. Run this after cleaning the glass."
        )
        view.addSubview_(self.calibrate_button)

        view.addSubview_(label("Cropping", NSMakeRect(24, 172, 200, 18), bold=True))
        view.addSubview_(label("Ignore anything smaller than", NSMakeRect(24, 144, 190, 18)))
        self.min_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(220, 139, 120, 26), False
        )
        self.min_popup.addItemsWithTitles_(['0.5"', '1"', '1.5"', '2"'])
        self.min_popup.setTarget_(self)
        self.min_popup.setAction_("changed:")
        view.addSubview_(self.min_popup)

        self.deskew_box = checkbox(
            "Straighten crooked photos", NSMakeRect(24, 110, 300, 20), self, "changed:"
        )
        self.trim_box = checkbox(
            "Trim leftover scanner background", NSMakeRect(24, 86, 300, 20), self, "changed:"
        )
        self.keep_box = checkbox(
            "Keep the full scan as well", NSMakeRect(24, 62, 300, 20), self, "changed:"
        )
        self.preview_box = checkbox(
            "Save a marked-up preview of each scan", NSMakeRect(24, 38, 340, 20), self, "changed:"
        )
        self.reveal_box = checkbox(
            "Open the folder when a scan finishes", NSMakeRect(24, 14, 340, 20), self, "changed:"
        )
        for box in (
            self.deskew_box,
            self.trim_box,
            self.keep_box,
            self.preview_box,
            self.reveal_box,
        ):
            view.addSubview_(box)

        self._load()
        return self

    @objc.python_method
    def show(self) -> None:
        self._load()
        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def close(self) -> None:
        self.window.orderOut_(None)

    @objc.python_method
    def _load(self) -> None:
        prefs = self.prefs
        home = str(Path.home())
        self.folder_field.setStringValue_(str(prefs.output_folder).replace(home, "~"))
        resolution = int(prefs["resolution"])
        if resolution in RESOLUTIONS:
            self.res_popup.selectItemAtIndex_(RESOLUTIONS.index(resolution))
        fmt = str(prefs["format"])
        if fmt in FORMATS:
            self.fmt_popup.selectItemAtIndex_(FORMATS.index(fmt))
        quality = int(prefs["quality"])
        self.quality_popup.selectItemAtIndex_(
            min(range(len(QUALITIES)), key=lambda i: abs(QUALITIES[i] - quality))
        )
        # Quality is a JPEG idea; PNG and TIFF are lossless either way.
        self.quality_popup.setEnabled_(fmt == "jpg")
        sizes = [0.5, 1.0, 1.5, 2.0]
        size = float(prefs["minSize"])
        self.min_popup.selectItemAtIndex_(
            min(range(len(sizes)), key=lambda i: abs(sizes[i] - size))
        )
        self.colour_box.setState_(1 if prefs["colour"] else 0)
        self.deskew_box.setState_(1 if prefs["deskew"] else 0)
        self.trim_box.setState_(1 if prefs["trim"] else 0)
        self.keep_box.setState_(1 if prefs["keepFullScan"] else 0)
        self.preview_box.setState_(1 if prefs["writePreview"] else 0)
        self.reveal_box.setState_(1 if prefs["revealWhenDone"] else 0)

    def changed_(self, sender) -> None:
        prefs = self.prefs
        prefs["resolution"] = RESOLUTIONS[self.res_popup.indexOfSelectedItem()]
        prefs["format"] = FORMATS[self.fmt_popup.indexOfSelectedItem()]
        prefs["quality"] = QUALITIES[self.quality_popup.indexOfSelectedItem()]
        prefs["minSize"] = [0.5, 1.0, 1.5, 2.0][self.min_popup.indexOfSelectedItem()]
        prefs["colour"] = bool(self.colour_box.state())
        prefs["deskew"] = bool(self.deskew_box.state())
        prefs["trim"] = bool(self.trim_box.state())
        prefs["keepFullScan"] = bool(self.keep_box.state())
        prefs["writePreview"] = bool(self.preview_box.state())
        prefs["revealWhenDone"] = bool(self.reveal_box.state())
        self.quality_popup.setEnabled_(str(prefs["format"]) == "jpg")
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

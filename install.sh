#!/bin/sh
# Set photosplit up on a Mac: virtualenv, dependencies, a command on your PATH,
# and a drag-and-drop app. Safe to re-run.
set -e
here=$(cd -- "$(dirname -- "$0")" && pwd)
cd "$here"

python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
echo "installed: $(./.venv/bin/python -c 'import cv2; print("opencv", cv2.__version__)')"

mkdir -p "$HOME/.local/bin"
ln -sf "$here/bin/photosplit" "$HOME/.local/bin/photosplit"
echo "command:   $HOME/.local/bin/photosplit"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "  note: add this to ~/.zshrc ->  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

rm -rf "$here/Photosplit.app"
osacompile -o "$here/Photosplit.app" - <<APPLESCRIPT
on run
	display dialog "Drop a scan (or a folder of scans) onto this app." buttons {"OK"} default button 1 with title "Photosplit"
end run

on open dropped
	set tool to quoted form of "$here/bin/photosplit"
	set args to ""
	repeat with item_ in dropped
		set args to args & " " & quoted form of POSIX path of item_
	end repeat
	try
		set report to do shell script tool & args & " --preview 2>&1"
		display dialog report buttons {"Show Files", "Done"} default button 1 with title "Photosplit"
		if button returned of result is "Show Files" then
			set first_ to item 1 of dropped
			tell application "Finder" to open ((container of (first_ as alias)) as alias)
		end if
	on error message_
		display alert "Photosplit could not finish" message message_ as warning
	end try
end open
APPLESCRIPT
echo "droplet:   $here/Photosplit.app  (drag it to your Dock)"

#!/bin/sh
# Build Photosplit.app.
#
# The bundle executable is a small shell script, but it does NOT exec the
# virtualenv's python directly: that binary lives inside Python.framework, so
# macOS would resolve the process back to Python.framework's own bundle and the
# app would show up as "Python" in the Dock and menu bar. Instead we copy the
# framework's launcher stub into our own MacOS folder and run that, which keeps
# the process inside this bundle. __PYVENV_LAUNCHER__ is what points the stub
# back at our virtualenv.
set -e
here=$(cd -- "$(dirname -- "$0")" && pwd)
app="$here/Photosplit.app"
py="$here/.venv/bin/python"

[ -x "$py" ] || { echo "no virtualenv yet — run ./install.sh first" >&2; exit 1; }

stub=$("$py" -c "import sys,pathlib; p=pathlib.Path(sys.base_prefix)/'Resources/Python.app/Contents/MacOS/Python'; print(p if p.exists() else '')")
real=$("$py" -c "import os,sys; print(os.path.realpath(sys.executable))")
venv_python=$("$py" -c "import sys,pathlib; print(pathlib.Path(sys.prefix)/'bin'/('python%d.%d'%sys.version_info[:2]))")

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"

"$py" "$here/make_icon.py" "$app/Contents/Resources/Photosplit.icns" >/dev/null

cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key><string>Photosplit</string>
	<key>CFBundleDisplayName</key><string>Photosplit</string>
	<key>CFBundleIdentifier</key><string>com.ericshiflet.photosplit</string>
	<key>CFBundleExecutable</key><string>Photosplit</string>
	<key>CFBundleIconFile</key><string>Photosplit</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleShortVersionString</key><string>1.0.0</string>
	<key>CFBundleVersion</key><string>1</string>
	<key>NSPrincipalClass</key><string>NSApplication</string>
	<key>NSHighResolutionCapable</key><true/>
	<key>LSMinimumSystemVersion</key><string>11.0</string>
	<key>CFBundleDocumentTypes</key>
	<array>
		<dict>
			<key>CFBundleTypeName</key><string>Scanned image</string>
			<key>CFBundleTypeRole</key><string>Viewer</string>
			<key>LSHandlerRank</key><string>Alternate</string>
			<key>LSItemContentTypes</key>
			<array><string>public.image</string><string>public.folder</string></array>
		</dict>
	</array>
</dict>
</plist>
PLIST

if [ -n "$stub" ]; then
	cp "$stub" "$app/Contents/MacOS/photosplit-python"
	chmod +x "$app/Contents/MacOS/photosplit-python"
	interpreter='"$here/photosplit-python"'
else
	echo "warning: no Python.app stub found; the app will show as \"Python\"" >&2
	interpreter="\"$real\""
fi

cat > "$app/Contents/MacOS/Photosplit" <<LAUNCHER
#!/bin/sh
# Photosplit.app/Contents/MacOS/ -> the repo three levels up.
here=\$(cd -- "\$(dirname -- "\$0")" && pwd)
repo=\$(cd -- "\$here/../../.." && pwd)
export __PYVENV_LAUNCHER__="$venv_python"
export PYTHONPATH="\$repo"
cd "\$repo"
exec $interpreter -m photosplit.app "\$@"
LAUNCHER
chmod +x "$app/Contents/MacOS/Photosplit"

codesign --force --deep --sign - "$app" >/dev/null 2>&1 || true
touch "$app"

# Build the interface once inside the finished bundle. Running the same code
# from a script does not prove it works here: the bundle has its own identity,
# and that alone has broken the app before.
if ! "$app/Contents/MacOS/Photosplit" --self-test; then
	echo "build failed: the app does not start from inside its bundle" >&2
	exit 1
fi
echo "built $app"

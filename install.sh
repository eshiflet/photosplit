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

"$here/build_app.sh" >/dev/null
echo "app:       $here/Photosplit.app  (drag it to your Dock)"

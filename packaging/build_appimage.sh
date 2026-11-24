#!/usr/bin/env bash
# Сборка Linux AppImage: PyInstaller (onedir) -> AppDir -> appimagetool.
#
# Требования: python3 с requirements.txt + pyinstaller, mksquashfs
# (squashfs-tools), curl. FUSE не обязателен — при его отсутствии
# appimagetool распаковывается через --appimage-extract.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_NAME="MediaTrimmer"
ARCH="${ARCH:-$(uname -m)}"
VERSION="$(tr -d '[:space:]' < version.txt)"
PYTHON="${PYTHON:-python3}"
WORK="$ROOT/build/appimage"
APPDIR="$WORK/AppDir"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"

export ARCH VERSION

command -v mksquashfs >/dev/null 2>&1 || {
    echo "Не найден mksquashfs — установите squashfs-tools" >&2
    exit 1
}

echo "==> PyInstaller (onedir)"
"$PYTHON" -m PyInstaller --noconfirm --clean \
    --distpath "$WORK/dist" --workpath "$WORK/work" \
    "$ROOT/packaging/media_trimmer.spec"

echo "==> AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -r "$WORK/dist/$APP_NAME" "$APPDIR/usr/bin/"
cp "$ROOT/packaging/media_trimmer.desktop" "$APPDIR/"
cp "$ROOT/packaging/media_trimmer.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT/packaging/media_trimmer.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/media-trimmer.png"
ln -sfn usr/share/icons/hicolor/256x256/apps/media-trimmer.png "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/MediaTrimmer/MediaTrimmer" "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo "==> appimagetool"
TOOL="$WORK/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" "$APPIMAGETOOL_URL"
    chmod +x "$TOOL"
fi

run_tool() {
    if APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$@"; then
        return 0
    fi
    echo "==> FUSE недоступен, распаковываем appimagetool"
    (cd "$WORK" && rm -rf squashfs-root && "$TOOL" --appimage-extract >/dev/null)
    "$WORK/squashfs-root/AppRun" "$@"
}

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/${APP_NAME}-${VERSION}-${ARCH}.AppImage"
rm -f "$OUT"
run_tool "$APPDIR" "$OUT"
chmod +x "$OUT"
echo "==> Готово: $OUT ($(du -h "$OUT" | cut -f1))"

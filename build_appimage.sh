#!/bin/bash
# AutoEnterScheduler AppImage 打包脚本
# 用法: ./build_appimage.sh

set -e

APP_NAME="AutoEnterScheduler"
APP_VERSION="1.1.1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/appimage-build"
APPDIR="$BUILD_DIR/$APP_NAME.AppDir"

echo "=== AutoEnterScheduler AppImage 打包 ==="
echo "版本: $APP_VERSION"
echo ""

# 清理旧构建
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# 1. 检查依赖
echo "[1/5] 检查依赖..."
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3"
    exit 1
fi

if ! python3 -c "import tkinter" &> /dev/null; then
    echo "错误: 未找到 python3-tk，请安装: sudo apt install python3-tk"
    exit 1
fi

if ! command -v pyinstaller &> /dev/null; then
    echo "安装 PyInstaller..."
    pip3 install pyinstaller
fi

# 2. 使用 PyInstaller 打包
echo "[2/5] 使用 PyInstaller 打包..."
cd "$SCRIPT_DIR"
pyinstaller --noconfirm --onefile --windowed \
    --name "$APP_NAME" \
    --distpath "$BUILD_DIR" \
    auto_enter_linux.py

# 3. 创建 AppDir 结构
echo "[3/5] 创建 AppDir 结构..."
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# 复制可执行文件
cp "$BUILD_DIR/$APP_NAME" "$APPDIR/usr/bin/"
chmod +x "$APPDIR/usr/bin/$APP_NAME"

# 复制图标
if [ -f "$SCRIPT_DIR/icon.png" ]; then
    cp "$SCRIPT_DIR/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APP_NAME.png"
    cp "$SCRIPT_DIR/icon.png" "$APPDIR/$APP_NAME.png"
fi

# 4. 创建桌面文件
echo "[4/5] 创建桌面文件..."
cat > "$APPDIR/$APP_NAME.desktop" << EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=定时自动回车工具
Exec=$APP_NAME
Icon=$APP_NAME
Categories=Utility;
Terminal=false
StartupNotify=true
EOF

cat > "$APPDIR/usr/share/applications/$APP_NAME.desktop" << EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=定时自动回车工具
Exec=$APP_NAME
Icon=$APP_NAME
Categories=Utility;
Terminal=false
StartupNotify=true
EOF

# 创建 AppRun
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin/:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib/:${LD_LIBRARY_PATH}"
exec "${HERE}/usr/bin/AutoEnterScheduler" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# 5. 打包成 AppImage
echo "[5/5] 打包成 AppImage..."
cd "$BUILD_DIR"

# 下载 appimagetool（如果不存在）
if [ ! -f "appimagetool" ]; then
    echo "下载 appimagetool..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        curl -L -o appimagetool "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    elif [ "$ARCH" = "aarch64" ]; then
        curl -L -o appimagetool "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-aarch64.AppImage"
    else
        echo "不支持的架构: $ARCH"
        exit 1
    fi
    chmod +x appimagetool
fi

# 生成 AppImage
OUTPUT="$SCRIPT_DIR/$APP_NAME-$APP_VERSION-x86_64.AppImage"
ARCH=x86_64 ./appimagetool "$APPDIR" "$OUTPUT"

echo ""
echo "=== 打包完成 ==="
echo "输出: $OUTPUT"
echo "大小: $(du -h "$OUTPUT" | cut -f1)"
echo ""
echo "使用方法:"
echo "  chmod +x $OUTPUT"
echo "  ./$OUTPUT"
echo ""
echo "依赖: 需要安装 xdotool (sudo apt install xdotool)"

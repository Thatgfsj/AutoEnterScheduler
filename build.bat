@echo off
chcp 65001 >nul
REM 打包脚本：单文件 exe，带图标，带窗口(无控制台)
cd /d "%~dp0"

echo [1/2] 生成图标...
python make_icon.py || goto :err

echo [2/2] PyInstaller 打包...
pyinstaller --noconfirm --onefile --windowed ^
  --name "AutoEnterScheduler" ^
  --icon icon.ico ^
  --add-data "icon.ico;." ^
  auto_enter.py || goto :err

echo.
echo === 打包完成 ===
echo 输出: dist\AutoEnterScheduler.exe
exit /b 0

:err
echo === 打包失败 ===
exit /b 1

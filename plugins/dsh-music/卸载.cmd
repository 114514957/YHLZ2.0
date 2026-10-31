@echo off
rem 双击卸载 dsh-music：删依赖行、bundle 行和 node_modules 里的 junction。
setlocal
cd /d "%~dp0"
echo === dsh-music uninstaller ===
node "%~dp0install.mjs" --uninstall --profile desktop
echo.
echo Restart DSH or press F5 to unload the plugin.
pause

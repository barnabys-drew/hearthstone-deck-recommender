@echo off
rem Start (or restart) the Hearthstone coach overlay.
rem Double-click this file, or pin a shortcut to it on the Desktop/taskbar.
rem Expects the app copy at %USERPROFILE%\hearthstone-overlay (see SKILL.md).

rem Kill any running overlay first; "not found" is fine.
taskkill /im electron.exe /f >nul 2>&1

rem cd first so everything below uses relative paths - cmd quoting of paths
rem with spaces is a known trap; this way there is nothing to quote.
cd /d "%USERPROFILE%\hearthstone-overlay" || (
  echo Could not find %USERPROFILE%\hearthstone-overlay & pause & exit /b 1
)

rem start "" detaches; the inner cmd /c exists only for the log redirection.
start "" /min cmd /c "node_modules\electron\dist\electron.exe . > electron.log 2>&1"

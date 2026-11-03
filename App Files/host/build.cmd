@echo off
rem Rebuilds ..\WikiApp.exe from WikiApp.cs using the C# compiler built into Windows.
rem Only needed after changing the C# host; the app itself (..\app) needs no build.
setlocal
cd /d "%~dp0"

set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
set FW=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319
set BIN=..\bin

if not exist app.ico powershell -NoProfile -ExecutionPolicy Bypass -File make-icon.ps1

"%CSC%" /nologo /target:winexe /platform:x64 /optimize+ ^
  /out:..\WikiApp.exe ^
  /win32icon:app.ico ^
  /resource:app.ico,WikiApp.app.ico ^
  /reference:%BIN%\Microsoft.Web.WebView2.Core.dll ^
  /reference:%BIN%\Microsoft.Web.WebView2.WinForms.dll ^
  /reference:System.Windows.Forms.dll ^
  /reference:System.Drawing.dll ^
  /reference:"%FW%\System.Web.Extensions.dll" ^
  WikiApp.cs

if errorlevel 1 (
  echo.
  echo Build FAILED.
) else (
  echo Built WikiApp.exe
)
if /i not "%~1"=="/nopause" pause

@echo off
rem Builds savebridge\_native\dsss_find.dll with MSVC (Visual Studio with the C++ tools).
setlocal EnableDelayedExpansion
set "ROOT=%~dp0.."
set "VS="
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq delims=" %%i in (`"!VSWHERE!" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS=%%i"
if not defined VS (echo Visual Studio with C++ tools not found & exit /b 1)
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
if not exist "%ROOT%\savebridge\_native" mkdir "%ROOT%\savebridge\_native"
cl /nologo /O2 /LD "%~dp0dsss_find.c" /Fe"%ROOT%\savebridge\_native\dsss_find.dll" /Fo"%TEMP%\dsss_find.obj" /link /IMPLIB:"%TEMP%\dsss_find.lib" >nul || exit /b 1
del "%ROOT%\savebridge\_native\dsss_find.exp" 2>nul
echo built savebridge\_native\dsss_find.dll

@echo off
rem Build lslint.exe (x64) with MSVC and winflexbison. Visual Studio Build Tools are enough, no IDE needed.
rem
rem Prerequisites:
rem   - Visual Studio Build Tools with the "Desktop development with C++" workload
rem     https://visualstudio.microsoft.com/visual-cpp-build-tools/
rem   - winflexbison unpacked in C:\flexandbison (or set WINFLEXBISON to its folder)
rem     https://github.com/lexxmark/winflexbison/releases
rem
rem Usage: build_win64.cmd [version] [debug]
rem   build_win64.cmd            -> lslint.exe version "dev"
rem   build_win64.cmd 1.2.0      -> lslint.exe version "1.2.0"
rem   build_win64.cmd dev debug   -> debuggable build (DEBUG=1 for nmake)
setlocal

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSPATH="
if exist "%VSWHERE%" (
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
)
if not defined VSPATH (
    for /d %%v in ("%ProgramFiles(x86)%\Microsoft Visual Studio\*") do (
        for /d %%e in ("%%v\*") do if exist "%%e\VC\Auxiliary\Build\vcvars64.bat" set "VSPATH=%%e"
    )
)
if not defined VSPATH (
    echo MSVC C++ toolset not found. Install Visual Studio Build Tools with the C++ workload.
    exit /b 1
)
call "%VSPATH%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1

if not defined WINFLEXBISON set "WINFLEXBISON=C:\flexandbison"
if not exist "%WINFLEXBISON%\win_flex.exe" (
    echo win_flex.exe not found in "%WINFLEXBISON%". Unpack winflexbison there or set WINFLEXBISON.
    exit /b 1
)
set "PATH=%WINFLEXBISON%;%PATH%"

if "%~1"=="" (set "BUILD_VERSION_NUMBER=dev") else (set "BUILD_VERSION_NUMBER=%~1")
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "BUILD_DATE=%%d"

if /i "%~2"=="debug" set "DEBUG=1"

cd /d "%~dp0"
rem Always start clean: objects compiled for the other CRT (debug/release) cannot be linked together.
nmake /NOLOGO /F NMakefile clean >nul 2>&1
nmake /NOLOGO /F NMakefile
if errorlevel 1 exit /b 1
echo.
echo Built lslint.exe %BUILD_VERSION_NUMBER% (%BUILD_DATE%)

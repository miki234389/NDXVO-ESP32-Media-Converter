@echo off
rem Launches NDXVO Media Converter from source.
rem Drag a video or image onto this file to open it straight away.
setlocal

rem Captured up front: %~dp0 can resolve against the new directory after cd
rem when this file was started through a relative path.
set "HERE=%~dp0"

rem Resolve the dropped/passed file before changing directory, so a relative
rem path given on the command line still points at the right file.
set "INPUT="
if not "%~1"=="" set "INPUT=%~f1"

cd /d "%HERE%"

rem Pick an interpreter: project venv first, then the py launcher, then PATH.
rem Each candidate is actually run, which skips the Microsoft Store stub that
rem "python" resolves to on a machine without a real install.
set "PYEXE="
if exist ".venv\Scripts\python.exe" call :probe .venv\Scripts\python.exe
if not defined PYEXE call :probe py -3
if not defined PYEXE call :probe python
if not defined PYEXE goto :no_python

rem Use pythonw.exe so no console window stays open behind the GUI.
set "PYWEXE=%PYEXE:python.exe=pythonw.exe%"
if not exist "%PYWEXE%" set "PYWEXE=%PYEXE%"

"%PYEXE%" -c "import PIL" >nul 2>&1
if not errorlevel 1 goto :launch
echo Pillow is not installed - installing it now...
"%PYEXE%" -m pip install pillow
if errorlevel 1 goto :pip_failed

:launch
if defined INPUT (
    start "" "%PYWEXE%" "%HERE%ndxvo_converter.py" "%INPUT%"
) else (
    start "" "%PYWEXE%" "%HERE%ndxvo_converter.py"
)
exit /b 0

:probe
for /f "delims=" %%i in ('%* -c "import sys; assert sys.hexversion >= 0x03090000; print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
exit /b 0

:no_python
echo Python 3.9 or newer was not found.
echo Install it from https://www.python.org/downloads/ and run this file again.
pause
exit /b 1

:pip_failed
echo.
echo Installing Pillow failed. Try manually:  "%PYEXE%" -m pip install pillow
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0.."
if /I "%~1"=="legacy" goto legacy
if not exist build mkdir build
if exist "tmp\rapfi_tools\w64devkit\bin\g++.exe" (
  "tmp\rapfi_tools\w64devkit\bin\g++.exe" -std=c++17 -O2 -DRAPFI_COURSE_DEBUG tests\rapfi_adapter.cpp -o build\rapfi_adapter.exe -Wl,--stack,8388608
  if errorlevel 1 exit /b 1
  goto run_rapfi
)
where cl >nul 2>nul
if errorlevel 1 call "D:\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cl /nologo /O2 /EHsc /std:c++17 /utf-8 /DRAPFI_COURSE_DEBUG tests\rapfi_adapter.cpp /Fe:build\rapfi_adapter.exe /Fo:build\rapfi_adapter.obj /link /STACK:8388608
if errorlevel 1 exit /b 1
:run_rapfi
build\rapfi_adapter.exe
if errorlevel 1 exit /b 1
python tests\protocol_test.py --engine build\gomoku.exe
exit /b %errorlevel%

:legacy
where cl >nul 2>nul
if errorlevel 1 call "D:\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if not exist build mkdir build
for %%T in (tactics oracle defense platform symmetry book_runtime book_engine) do (
  cl /nologo /O2 /EHsc /std:c++17 /W4 /utf-8 tests\%%T.cpp /Fe:build\%%T.exe /Fo:build\%%T.obj
  if errorlevel 1 exit /b 1
  build\%%T.exe
  if errorlevel 1 exit /b 1
)
exit /b 0

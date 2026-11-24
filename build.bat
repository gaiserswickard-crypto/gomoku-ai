@echo off
setlocal
cd /d "%~dp0"
if not exist build mkdir build
where g++ >nul 2>nul
if not errorlevel 1 goto gcc
if exist "tmp\rapfi_tools\w64devkit\bin\g++.exe" goto portable_gcc
where cl >nul 2>nul
if errorlevel 1 (
  if exist "D:\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
    call "D:\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
  ) else (
    echo Please run from an MSVC x64 Native Tools prompt, or install g++.
    exit /b 1
  )
)
cl /nologo /O2 /EHsc /std:c++17 /W4 /utf-8 main.cpp /Fe:build\gomoku.exe /Fo:build\gomoku.obj /link /STACK:8388608
exit /b %errorlevel%

:gcc
g++ -std=c++17 -O2 -Wall -Wextra -pedantic main.cpp -o build\gomoku.exe -Wl,--stack,8388608
exit /b %errorlevel%

:portable_gcc
"tmp\rapfi_tools\w64devkit\bin\g++.exe" -std=c++17 -O2 -Wall -Wextra -pedantic main.cpp -o build\gomoku.exe -Wl,--stack,8388608
exit /b %errorlevel%

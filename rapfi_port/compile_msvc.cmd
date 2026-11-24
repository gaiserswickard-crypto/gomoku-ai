@echo off
setlocal
call "D:\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++17 /O2 /EHsc /DNDEBUG /utf-8 rapfi_trained.cpp /Fe:rapfi_trained_msvc.exe /Fo:rapfi_trained_msvc.obj /link /STACK:8388608
exit /b %errorlevel%

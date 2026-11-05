@echo off
rem build llama-cvector-generator via vcvars64 + ninja (CPU only, release)
chcp 65001 >nul
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 ( echo VCVARS_FAIL & exit /b 1 )
set "PATH=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%"
cd /d "C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\llama-cuda\src\llama.cpp-b10991"
echo [1/2] configure...
cmake -B build-cvec -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF
if errorlevel 1 goto fail
echo [2/2] build...
cmake --build build-cvec --target llama-cvector-generator -j 14
if errorlevel 1 goto fail
echo BUILD_OK
dir /s /b build-cvec\*cvector*.exe
exit /b 0
:fail
echo BUILD_FAIL
exit /b 1

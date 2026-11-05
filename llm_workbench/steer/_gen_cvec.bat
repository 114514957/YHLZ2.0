@echo off
rem generate control vector: 元亨 (short/blunt) vs 客服腔 (long/question)
chcp 65001 >nul
set "BIN=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\llama-cuda\src\llama.cpp-b10991\build-cvec\bin"
set "MODEL=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\gemma4-gguf\gemma-4-E4B_q4_0-it.gguf"
set "STEER=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\steer"
cd /d "%BIN%"
set PATH=%BIN%;%PATH%
llama-cvector-generator.exe -m "%MODEL%" --positive-file "%STEER%\positive.txt" --negative-file "%STEER%\negative.txt" --method mean -o "%STEER%\cvec_style_mean.gguf" -c 1024
echo EXIT=%errorlevel%
dir "%STEER%\cvec_style_mean.gguf" 2>nul

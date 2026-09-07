@echo off
chcp 65001 >nul
rem Gemma-4-E4B-Aggressive 第二专用模型服务（llama.cpp 内核，端口 8081）
rem 用途：长上下文/多模态（Embodied vision）研究；不用作本地记忆 consolidate 链路
set LS=C:\Users\ACE_WAN——PROJECT\AppData\Local\Programs\Ollama\lib\ollama\llama-server.exe
set M=C:\Users\ACE_WAN——PROJECT\models\gemma4\gemma4-e4b-aggr-q4km.gguf
set P=C:\Users\ACE_WAN——PROJECT\models\gemma4\mmproj-gemma4-e4b.gguf
"%LS%" -m "%M%" --mmproj "%P%" -c 8192 --port 8081 --host 127.0.0.1 --temp 1.0 --top-p 0.95 --top-k 64

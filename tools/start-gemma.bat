@echo off
chcp 65001 >nul
rem Gemma-4-E4B-Aggressive 元亨主服务（llama.cpp 完整版, :8081）
rem --reasoning off = 关 cot(思考)全局=直接作答,响应快且人格不漂移(ledger 0212)
set LS=C:\Users\ACE_WAN——PROJECT\AppData\Local\Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server.exe
set M=C:\Users\ACE_WAN——PROJECT\models\gemma4\gemma4-e4b-aggr-q4km.gguf
set P=C:\Users\ACE_WAN——PROJECT\models\gemma4\mmproj-gemma4-e4b.gguf
"%LS%" -m "%M%" --mmproj "%P%" --jinja --reasoning off -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -c 8192 --port 8081 --host 127.0.0.1 --temp 1.0 --top-p 0.95 --top-k 64

"""
YHLZ 2.0 WebUI 服务
基于Flask实现Web界面
支持启动、退出、日志功能
端口: 5000 (WebUI), 8000 (后端API), 8081 (Live2D)
"""

import os
import sys
import json
import time
import signal
import logging
import threading
import subprocess
import platform
import psutil
import webbrowser
import atexit
import socket
from pathlib import Path
from datetime import datetime

# 统一 UTF-8 编码 (避免 Windows 下中文/emoji 乱码)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from flask import Flask, render_template, jsonify, request, send_from_directory, Response
from flask_cors import CORS

# 配置日志
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f"webui_{datetime.now().strftime('%Y%m%d')}.log"
config_file = log_dir.parent / "webui_config.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("YHLZ.WebUI")

app = Flask(__name__, static_folder='webui_static', template_folder='webui_templates')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
CORS(app)

# 服务状态
services_status = {
    "webui": {"status": "running", "port": 5000, "pid": os.getpid()},
    "backend": {"status": "stopped", "port": 8000, "pid": None},
    "live2d": {"status": "stopped", "port": 8081, "pid": None},
    "asr": {"status": "stopped", "port": None, "pid": None},
    "tts": {"status": "stopped", "port": None, "pid": None},
    "voice_chat": {"status": "stopped", "port": None, "pid": None},
    "avatar": {"status": "stopped", "port": None, "pid": None}
}

# 进程引用
backend_process = None
live2d_process = None
avatar_process = None
vision_process = None

# 服务运行状态标志（用于 ASR/TTS 等不需要单独进程的服务）
asr_running = False
tts_running = False

# 虚拟形象状态
avatar_status = {"running": False, "pid": None}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    """获取所有服务状态"""
    global asr_running, tts_running, avatar_process, backend_process, live2d_process, avatar_status, services_status
    
    # 检查端口状态的服务（排除 live2d 和 avatar，它们用进程状态检查）
    for name, info in services_status.items():
        port = info.get('port')
        if port and name not in ('webui', 'live2d', 'avatar'):
            info['status'] = 'running' if is_port_in_use(port) else 'stopped'
    
    # 检查进程/标志状态的服务
    services_status['asr']['status'] = 'running' if asr_running else 'stopped'
    services_status['tts']['status'] = 'running' if tts_running else 'stopped'
    services_status['voice_chat']['status'] = 'running' if (asr_running and tts_running) else 'stopped'
    
    # 检查 live2d 桌宠进程状态
    if live2d_process and live2d_process.poll() is None:
        services_status['live2d']['status'] = 'running'
        services_status['live2d']['pid'] = live2d_process.pid
    else:
        services_status['live2d']['status'] = 'stopped'
        services_status['live2d']['pid'] = None
        if live2d_process and live2d_process.poll() is not None:
            live2d_process = None
    
    # 检查虚拟形象进程状态
    if avatar_process and avatar_process.poll() is None:
        services_status['avatar']['status'] = 'running'
        avatar_status['running'] = True
    else:
        services_status['avatar']['status'] = 'stopped'
        avatar_status['running'] = False
        if avatar_process and avatar_process.poll() is not None:
            avatar_process = None
    
    return jsonify(services_status)

@app.route('/api/avatar/start', methods=['POST'])
def start_avatar():
    """启动虚拟形象"""
    global avatar_process, avatar_status, services_status
    try:
        if avatar_status['running'] and avatar_process and avatar_process.poll() is None:
            return jsonify({"success": False, "message": "虚拟形象已在运行"})
        
        # 如果之前的进程已退出，清理状态
        if avatar_process and avatar_process.poll() is not None:
            avatar_process = None
            avatar_status['running'] = False
        
        # 优先使用 live2d_qt_avatar.py（PyQt5 + QOpenGLWidget 渲染版）
        avatar_script = Path(__file__).parent / "live2d_qt_avatar.py"
        if not avatar_script.exists():
            avatar_script = Path(__file__).parent / "live2d_pygame_avatar.py"
        if not avatar_script.exists():
            avatar_script = Path(__file__).parent / "avatar_main.py"
        
        if not avatar_script.exists():
            return jsonify({"success": False, "message": "找不到虚拟形象脚本"})
        
        # 使用 DEVNULL 避免管道死锁问题
        avatar_process = subprocess.Popen(
            [sys.executable, str(avatar_script)],
            cwd=str(Path(__file__).parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        # 等待启动（给更多时间让Qt初始化）
        time.sleep(3)
        
        # 检查进程是否在运行
        if avatar_process.poll() is not None:
            error_msg = f"虚拟形象启动失败，进程已退出 (退出码: {avatar_process.returncode})"
            logger.error(error_msg)
            avatar_process = None
            avatar_status['running'] = False
            services_status['avatar']['status'] = 'stopped'
            return jsonify({"success": False, "message": error_msg}), 500
        
        # 验证窗口是否真的存在
        if sys.platform == 'win32':
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.FindWindowW(None, "元亨桌宠")
                if not hwnd:
                    # 进程在但窗口没找到，可能还在加载中，再多等一会
                    time.sleep(2)
                    hwnd = user32.FindWindowW(None, "元亨桌宠")
                    if not hwnd:
                        logger.warning("虚拟形象窗口未找到，但进程在运行")
            except Exception as e:
                logger.warning(f"窗口验证失败: {e}")
        
        avatar_status['running'] = True
        avatar_status['pid'] = avatar_process.pid
        services_status['avatar'] = {"status": "running", "port": None, "pid": avatar_process.pid}
        logger.info(f"虚拟形象启动成功 PID: {avatar_process.pid}")
        return jsonify({"success": True, "message": "虚拟形象启动成功"})
    except Exception as e:
        logger.error(f"启动虚拟形象失败: {e}")
        avatar_status['running'] = False
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/avatar/stop', methods=['POST'])
def stop_avatar():
    """停止虚拟形象"""
    global avatar_process, avatar_status, services_status
    try:
        if avatar_process and avatar_process.poll() is None:
            avatar_process.terminate()
            try:
                avatar_process.wait(timeout=5)
            except:
                avatar_process.kill()
            avatar_process = None
        
        avatar_status['running'] = False
        avatar_status['pid'] = None
        services_status['avatar'] = {"status": "stopped", "port": None, "pid": None}
        logger.info("虚拟形象已停止")
        return jsonify({"success": True, "message": "虚拟形象已停止"})
    except Exception as e:
        logger.error(f"停止虚拟形象失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/avatar/status')
def get_avatar_status():
    """获取虚拟形象状态"""
    return jsonify(avatar_status)

@app.route('/api/services/<service_name>/start', methods=['POST'])
def start_service(service_name):
    global backend_process, live2d_process, asr_running, tts_running
    
    try:
        if service_name == 'backend':
            # 检查现有进程状态
            if backend_process and backend_process.poll() is None:
                # 进程存在，检查端口是否真的在监听
                if is_port_in_use(8000):
                    return jsonify({"success": False, "message": "后端服务已在运行"}), 400
                else:
                    # 僵尸进程，清理它
                    logger.warning("发现僵尸后端进程，正在清理...")
                    backend_process.terminate()
                    try:
                        backend_process.wait(timeout=3)
                    except:
                        backend_process.kill()
                    backend_process = None
            
            # 检查端口是否已被占用（可能是通过其他方式启动的后端）
            if is_port_in_use(8000):
                services_status['backend']['status'] = 'running'
                logger.info("后端服务已在端口8000上运行")
                return jsonify({"success": True, "message": "后端服务已在运行"})
            
            backend_script = Path(__file__).parent / "backend" / "main.py"
            if not backend_script.exists():
                return jsonify({"success": False, "message": f"后端脚本不存在: {backend_script}"}), 404
            
            # 启动后端，重定向输出到日志文件
            log_dir = Path(__file__).parent / "logs"
            log_dir.mkdir(exist_ok=True)
            stdout_file = open(log_dir / "backend_stdout.log", "w", encoding="utf-8")
            stderr_file = open(log_dir / "backend_stderr.log", "w", encoding="utf-8")

            backend_process = subprocess.Popen(
                [sys.executable, str(backend_script)],
                cwd=str(Path(__file__).parent),
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            # 后台线程等待服务就绪 + 自动重启监控
            def wait_backend():
                global backend_process
                # 等待启动
                for i in range(60):
                    time.sleep(1)
                    if backend_process.poll() is not None:
                        services_status['backend']['status'] = 'stopped'
                        logger.error(f"后端启动失败（进程退出 code={backend_process.returncode}），请查看 logs/backend_stderr.log")
                        return
                    if is_port_in_use(8000):
                        services_status['backend']['status'] = 'running'
                        services_status['backend']['pid'] = backend_process.pid
                        logger.info(f"后端服务启动成功 PID: {backend_process.pid} (耗时 {i+1}s)")
                        break
                else:
                    services_status['backend']['status'] = 'stopped'
                    logger.warning("后端服务启动超时(60s)")
                    return

                # 自动重启监控：进程意外退出时自动重启（最多3次）
                restart_count = 0
                max_restarts = 3
                while restart_count < max_restarts:
                    time.sleep(5)
                    if backend_process.poll() is not None:
                        restart_count += 1
                        logger.warning(f"后端进程意外退出(code={backend_process.returncode})，第 {restart_count}/{max_restarts} 次自动重启...")
                        if restart_count >= max_restarts:
                            services_status['backend']['status'] = 'stopped'
                            logger.error("后端自动重启次数已达上限，请手动检查日志")
                            return
                        time.sleep(2)
                        # 重新打开日志文件
                        stdout_file2 = open(log_dir / "backend_stdout.log", "a", encoding="utf-8")
                        stderr_file2 = open(log_dir / "backend_stderr.log", "a", encoding="utf-8")
                        backend_process = subprocess.Popen(
                            [sys.executable, str(backend_script)],
                            cwd=str(Path(__file__).parent),
                            stdout=stdout_file2,
                            stderr=stderr_file2,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                        )
                        logger.info(f"后端重启中 PID: {backend_process.pid}")
                        for i in range(60):
                            time.sleep(1)
                            if backend_process.poll() is not None:
                                break
                            if is_port_in_use(8000):
                                services_status['backend']['status'] = 'running'
                                services_status['backend']['pid'] = backend_process.pid
                                logger.info(f"后端重启成功 PID: {backend_process.pid}")
                                break
                    elif not is_port_in_use(8000):
                        # 进程活着但端口没了，可能卡死了
                        logger.warning("后端进程存活但端口8000无响应，可能卡死")
                        backend_process.terminate()
                        try:
                            backend_process.wait(timeout=5)
                        except:
                            backend_process.kill()

            threading.Thread(target=wait_backend, daemon=True).start()
            logger.info(f"后端服务启动中 PID: {backend_process.pid}")
            return jsonify({"success": True, "message": "后端服务启动中，请稍候..."})
            
        elif service_name == 'live2d':
            # 检查现有进程状态
            if live2d_process and live2d_process.poll() is None:
                return jsonify({"success": False, "message": "桌宠已在运行"}), 400
            
            # 清理僵尸进程
            if live2d_process and live2d_process.poll() is not None:
                live2d_process = None
            
            # 使用 live2d_qt_avatar.py（PyQt5 + QOpenGLWidget）
            live2d_script = Path(__file__).parent / "live2d_qt_avatar.py"
            if not live2d_script.exists():
                live2d_script = Path(__file__).parent / "live2d_pygame_avatar.py"
            if not live2d_script.exists():
                return jsonify({"success": False, "message": "桌宠脚本不存在"}), 404
            
            live2d_process = subprocess.Popen(
                [sys.executable, str(live2d_script)],
                cwd=str(Path(__file__).parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            # 等待几秒检查进程是否存活
            time.sleep(2)
            if live2d_process.poll() is not None:
                services_status['live2d']['status'] = 'stopped'
                logger.error(f"桌宠启动失败（进程退出，退出码: {live2d_process.returncode}）")
                live2d_process = None
                return jsonify({"success": False, "message": f"桌宠启动失败，退出码: {live2d_process.returncode}"}), 500
            
            services_status['live2d']['status'] = 'running'
            services_status['live2d']['pid'] = live2d_process.pid
            logger.info(f"桌宠启动成功 PID: {live2d_process.pid}")
            return jsonify({"success": True, "message": "桌宠形象启动成功"})
        
        elif service_name == 'voice_chat':
            if asr_running and tts_running:
                return jsonify({"success": False, "message": "语音对话已在运行"}), 400

            # 加载 ASR 模型（异步，不阻塞）
            try:
                import requests as req
                r = req.post('http://localhost:8000/modules/start',
                           json={"module_name": "asr"}, timeout=30)
                logger.info(f"ASR模块加载: {r.json().get('message', '')}")
            except Exception as e:
                logger.warning(f"ASR模块加载失败(非致命): {e}")

            asr_running = True
            tts_running = True
            services_status['asr']['status'] = 'running'
            services_status['tts']['status'] = 'running'
            services_status['voice_chat']['status'] = 'running'
            logger.info("语音对话服务已启动（ASR+TTS）")
            return jsonify({"success": True, "message": "语音对话已启动"})

        elif service_name == 'asr':
            if asr_running:
                return jsonify({"success": False, "message": "ASR已在运行"}), 400

            # ASR 通过后端 API 调用，不需要单独进程
            asr_running = True
            services_status['asr']['status'] = 'running'
            logger.info("ASR服务已启动（通过后端API调用）")
            return jsonify({"success": True, "message": "ASR服务启动成功"})

        elif service_name == 'tts':
            if tts_running:
                return jsonify({"success": False, "message": "TTS已在运行"}), 400

            # TTS 通过后端 API 调用，不需要单独进程
            tts_running = True
            services_status['tts']['status'] = 'running'
            logger.info("TTS服务已启动（通过后端API调用）")
            return jsonify({"success": True, "message": "TTS服务启动成功"})
        
        elif service_name == 'avatar':
            return start_avatar()
            
        else:
            return jsonify({"success": False, "message": f"未知服务: {service_name}"}), 404
            
    except Exception as e:
        logger.error(f"启动服务失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/services/<service_name>/stop', methods=['POST'])
def stop_service(service_name):
    global backend_process, live2d_process, asr_running, tts_running
    
    try:
        if service_name == 'backend':
            if backend_process and backend_process.poll() is None:
                backend_process.terminate()
                backend_process.wait(timeout=5)
                backend_process = None
            services_status['backend']['status'] = 'stopped'
            services_status['backend']['pid'] = None
            logger.info("后端服务已停止")
            return jsonify({"success": True, "message": "后端服务已停止"})
            
        elif service_name == 'live2d':
            if live2d_process and live2d_process.poll() is None:
                live2d_process.terminate()
                live2d_process.wait(timeout=5)
                live2d_process = None
            services_status['live2d']['status'] = 'stopped'
            services_status['live2d']['pid'] = None
            logger.info("Live2D服务已停止")
            return jsonify({"success": True, "message": "Live2D服务已停止"})

        elif service_name == 'voice_chat':
            if asr_running or tts_running:
                asr_running = False
                tts_running = False
                services_status['asr']['status'] = 'stopped'
                services_status['tts']['status'] = 'stopped'
                services_status['voice_chat']['status'] = 'stopped'
                # 卸载 ASR 模型释放显存
                try:
                    import requests as req
                    req.post('http://localhost:8000/modules/stop',
                           json={"module_name": "asr"}, timeout=10)
                    logger.info("ASR模块已卸载")
                except Exception:
                    pass
                logger.info("语音对话服务已停止")
            return jsonify({"success": True, "message": "语音对话已停止"})

        elif service_name == 'asr':
            if asr_running:
                asr_running = False
                services_status['asr']['status'] = 'stopped'
                logger.info("ASR服务已停止")
            return jsonify({"success": True, "message": "ASR服务已停止"})

        elif service_name == 'tts':
            if tts_running:
                tts_running = False
                services_status['tts']['status'] = 'stopped'
                logger.info("TTS服务已停止")
            return jsonify({"success": True, "message": "TTS服务已停止"})
        
        elif service_name == 'avatar':
            return stop_avatar()
            
        else:
            return jsonify({"success": False, "message": f"未知服务: {service_name}"}), 404
            
    except Exception as e:
        logger.error(f"停止服务失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/services/start_all', methods=['POST'])
def start_all():
    """启动所有服务"""
    results = {}
    try:
        for service in ['backend', 'asr', 'tts', 'avatar']:
            resp = start_service(service)
            # 处理可能返回的元组 (response, status_code)
            if isinstance(resp, tuple):
                resp = resp[0]  # 取出 Response 对象
            results[service] = resp.get_json()
        return jsonify(results)
    except Exception as e:
        logger.error(f"启动所有服务失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/services/stop_all', methods=['POST'])
def stop_all():
    results = {}
    try:
        for service in ['avatar', 'live2d', 'backend', 'asr', 'tts']:
            resp = stop_service(service)
            if isinstance(resp, tuple):
                resp = resp[0]
            results[service] = resp.get_json()
        return jsonify(results)
    except Exception as e:
        logger.error(f"停止所有服务失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/logs')
def get_logs():
    log_lines = request.args.get('lines', 100, type=int)
    try:
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            return jsonify({"logs": lines[-log_lines:], "total_lines": len(lines)})
        return jsonify({"logs": [], "total_lines": 0})
    except Exception as e:
        return jsonify({"logs": [], "error": str(e)})

@app.route('/api/logs/backend')
def get_backend_logs():
    log_lines = request.args.get('lines', 100, type=int)
    backend_log = Path(__file__).parent / "backend.log"
    try:
        if backend_log.exists():
            with open(backend_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            return jsonify({"logs": lines[-log_lines:], "total_lines": len(lines)})
        return jsonify({"logs": [], "total_lines": 0})
    except Exception as e:
        return jsonify({"logs": [], "error": str(e)})

@app.route('/api/memory/clear', methods=['POST'])
def clear_memory():
    """清空记忆数据"""
    try:
        memory_dir = Path(__file__).parent / "memory"
        if memory_dir.exists():
            import shutil
            shutil.rmtree(memory_dir)
            memory_dir.mkdir(exist_ok=True)
        logger.info("记忆数据已清空")
        return jsonify({"success": True, "message": "记忆数据已清空"})
    except Exception as e:
        logger.error(f"清空记忆失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/memory/stats')
def get_memory_stats():
    """获取记忆统计"""
    try:
        memory_dir = Path(__file__).parent / "memory"
        memory_dir.mkdir(exist_ok=True)
        
        session_count = 0
        knowledge_count = 0
        preference_count = 0
        
        for f in memory_dir.glob("*.json"):
            if "session" in f.name:
                session_count += 1
            elif "knowledge" in f.name:
                knowledge_count += 1
            elif "preference" in f.name:
                preference_count += 1
        
        return jsonify({
            "sessions": session_count,
            "knowledge": knowledge_count,
            "preferences": preference_count
        })
    except Exception as e:
        return jsonify({"sessions": 0, "knowledge": 0, "preferences": 0})

@app.route('/api/config')
def get_config():
    env_file = Path(__file__).parent / ".env"
    config = {}
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if 'KEY' not in key.upper() and 'SECRET' not in key.upper():
                        config[key] = value
    return jsonify(config)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    message = data.get('message', '')
    tts_enabled = data.get('tts_enabled', False)

    try:
        import requests as req
        resp = req.post(
            'http://localhost:8000/chat',
            json={
                "text": message,
                "tts_enabled": tts_enabled,
                "use_tools": True
            },
            timeout=30
        )
        # 后端 /chat 为 SSE 流式: 逐行转发 (兼容非流式调用方)
        def proxy_stream():
            for line in resp.iter_lines():
                if line:
                    yield line.decode('utf-8', errors='replace') + '\n\n'
        return Response(proxy_stream(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache'})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== V2.2 声音克隆代理 ====================

import requests as _voice_req  # 模块级 import, 保证 except 可用

@app.route('/api/voice/clone', methods=['POST'])
def voice_clone_proxy():
    """代理到 backend POST /voice/clone (multipart 转发)"""
    try:
        audio = request.files.get('audio')
        if audio is None:
            return jsonify({"success": False, "error": "缺少 audio 文件", "stage": "validate"}), 400
        files = {'audio': (audio.filename, audio.read(), audio.mimetype)}
        data = {
            'name': request.form.get('name', ''),
            'engine': request.form.get('engine', 'qwen3'),
            'voice_id': request.form.get('voice_id', '') or '',
            'language': request.form.get('language', 'zh'),
            'metadata': request.form.get('metadata', '') or '',
        }
        if not data['name']:
            return jsonify({"success": False, "error": "缺少 name 参数", "stage": "validate"}), 400
        resp = _voice_req.post(
            'http://localhost:8000/voice/clone',
            files=files, data=data, timeout=120,
        )
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动 (请先启动 :8000)", "stage": "service_init"}), 503
    except Exception as e:
        logger.error(f"voice_clone_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e), "stage": "proxy"}), 500

@app.route('/api/voice/synthesize', methods=['POST'])
def voice_synthesize_proxy():
    """代理到 backend POST /voice/synthesize"""
    try:
        data = request.get_json() or request.form.to_dict()
        resp = _voice_req.post(
            'http://localhost:8000/voice/synthesize',
            data=data, timeout=60,
        )
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_synthesize_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== Phase 2.1 / 2.2 / 2.3 代理 ====================

@app.route('/api/voice/list', methods=['GET'])
def voice_list_proxy():
    """代理到 backend GET /voice/list"""
    try:
        resp = _voice_req.get('http://localhost:8000/voice/list', timeout=15)
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_list_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/<voice_id>', methods=['GET'])
def voice_detail_proxy(voice_id):
    """代理到 backend GET /voice/<voice_id>"""
    try:
        resp = _voice_req.get(f'http://localhost:8000/voice/{voice_id}', timeout=15)
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_detail_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/<voice_id>', methods=['DELETE'])
def voice_delete_proxy(voice_id):
    """代理到 backend DELETE /voice/<voice_id>"""
    try:
        soft = request.args.get('soft', 'false').lower() == 'true'
        resp = _voice_req.delete(
            f'http://localhost:8000/voice/{voice_id}',
            params={"soft": str(soft).lower()}, timeout=30,
        )
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_delete_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/uploads/cleanup', methods=['POST'])
def voice_cleanup_ttl_proxy():
    """代理到 backend POST /voice/uploads/cleanup"""
    try:
        resp = _voice_req.post('http://localhost:8000/voice/uploads/cleanup', timeout=30)
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_cleanup_ttl_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/uploads/cleanup-all', methods=['DELETE'])
def voice_cleanup_all_proxy():
    """代理到 backend DELETE /voice/uploads/cleanup-all"""
    try:
        resp = _voice_req.delete('http://localhost:8000/voice/uploads/cleanup-all', timeout=30)
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_cleanup_all_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/quality/evaluate', methods=['POST'])
def voice_quality_proxy():
    """代理到 backend POST /voice/quality/evaluate (multipart)"""
    try:
        ref = request.files.get('reference_audio')
        syn = request.files.get('synthesized_audio')
        if ref is None or syn is None:
            return jsonify({"success": False, "error": "缺少音频文件"}), 400
        files = {
            'reference_audio': (ref.filename, ref.read(), ref.mimetype),
            'synthesized_audio': (syn.filename, syn.read(), syn.mimetype),
        }
        data = {
            'reference_text': request.form.get('reference_text', '') or '',
            'use_asr': request.form.get('use_asr', 'false'),
        }
        resp = _voice_req.post(
            'http://localhost:8000/voice/quality/evaluate',
            files=files, data=data, timeout=120,
        )
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_quality_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/adapters/dashboard', methods=['GET'])
def voice_adapters_dashboard_proxy():
    """代理到 backend GET /voice/adapters/dashboard"""
    try:
        resp = _voice_req.get('http://localhost:8000/voice/adapters/dashboard', timeout=15)
        return jsonify(resp.json())
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_adapters_dashboard_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/audio/<voice_id>', methods=['GET'])
def voice_audio_proxy(voice_id):
    """代理到 backend GET /voice/audio/<voice_id> (音频流)"""
    try:
        resp = _voice_req.get(f'http://localhost:8000/voice/audio/{voice_id}', timeout=30, stream=True)
        if resp.status_code != 200:
            return jsonify(resp.json()), resp.status_code
        return Response(
            resp.iter_content(chunk_size=8192),
            content_type=resp.headers.get('content-type', 'audio/wav'),
        )
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_audio_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ===== Phase 3.1 批量克隆 =====
@app.route('/api/voice/clone/batch', methods=['POST'])
def voice_clone_batch_proxy():
    """代理到 backend POST /voice/clone/batch (multipart)"""
    try:
        resp = _voice_req.post(
            'http://localhost:8000/voice/clone/batch',
            data=request.form, timeout=30,
        )
        return jsonify(resp.json()), resp.status_code
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_clone_batch_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/clone/batch', methods=['GET'])
def voice_clone_batch_list_proxy():
    """代理到 backend GET /voice/clone/batch (列表)"""
    try:
        limit = request.args.get('limit', '50')
        resp = _voice_req.get(f'http://localhost:8000/voice/clone/batch?limit={limit}', timeout=15)
        return jsonify(resp.json()), resp.status_code
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_clone_batch_list_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/clone/batch/<task_id>', methods=['GET'])
def voice_clone_batch_status_proxy(task_id):
    """代理到 backend GET /voice/clone/batch/<task_id>"""
    try:
        resp = _voice_req.get(f'http://localhost:8000/voice/clone/batch/{task_id}', timeout=15)
        return jsonify(resp.json()), resp.status_code
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_clone_batch_status_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/clone/batch/<task_id>/cancel', methods=['POST'])
def voice_clone_batch_cancel_proxy(task_id):
    """代理到 backend POST /voice/clone/batch/<task_id>/cancel"""
    try:
        resp = _voice_req.post(f'http://localhost:8000/voice/clone/batch/{task_id}/cancel', timeout=15)
        return jsonify(resp.json()), resp.status_code
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_clone_batch_cancel_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ===== Phase 3.2 声音去重 =====
@app.route('/api/voice/duplicate/check', methods=['POST'])
def voice_duplicate_check_proxy():
    """代理到 backend POST /voice/duplicate/check (multipart)"""
    try:
        files = {'audio': (request.files['audio'].filename, request.files['audio'].stream, request.files['audio'].mimetype)} if 'audio' in request.files else None
        data = request.form
        resp = _voice_req.post(
            'http://localhost:8000/voice/duplicate/check',
            files=files, data=data, timeout=60,
        )
        return jsonify(resp.json()), resp.status_code
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_duplicate_check_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ===== Phase 3.3 安全审计 =====
@app.route('/api/voice/audit/log', methods=['GET'])
def voice_audit_log_proxy():
    """代理到 backend GET /voice/audit/log"""
    try:
        resp = _voice_req.get('http://localhost:8000/voice/audit/log', params=request.args, timeout=15)
        return jsonify(resp.json()), resp.status_code
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_audit_log_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/audit/count', methods=['GET'])
def voice_audit_count_proxy():
    """代理到 backend GET /voice/audit/count"""
    try:
        resp = _voice_req.get('http://localhost:8000/voice/audit/count', params=request.args, timeout=15)
        return jsonify(resp.json()), resp.status_code
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_audit_count_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/voice/audit/permission/<voice_id>', methods=['GET'])
def voice_audit_permission_proxy(voice_id):
    """代理到 backend GET /voice/audit/permission/<voice_id>"""
    try:
        resp = _voice_req.get(f'http://localhost:8000/voice/audit/permission/{voice_id}', params=request.args, timeout=15)
        return jsonify(resp.json()), resp.status_code
    except _voice_req.exceptions.ConnectionError:
        return jsonify({"success": False, "error": "后端服务未启动"}), 503
    except Exception as e:
        logger.error(f"voice_audit_permission_proxy 异常: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/health')
def health_check():
    try:
        import requests as req
        resp = req.get('http://localhost:8000/health', timeout=5)
        data = resp.json()
        # 状态归一化: 后端 healthy/ok 均视为正常 (前端判定 status === 'ok')
        if data.get('status') in ('healthy', 'ok'):
            data['status'] = 'ok'
        return jsonify(data)
    except:
        return jsonify({"status": "unhealthy", "message": "后端服务未运行"})

@app.route('/api/system/info')
def get_system_info():
    """获取系统信息"""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return jsonify({
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu": {
                "usage_percent": cpu_percent,
                "cores": psutil.cpu_count()
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "percent": memory.percent
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "percent": disk.percent
            },
            "gpu": _get_gpu_info()
        })
    except Exception as e:
        return jsonify({"error": str(e)})

def _get_gpu_info():
    """获取GPU信息（如果可用）"""
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total,memory.used,utilization.gpu',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            gpus = []
            for line in result.stdout.strip().split('\n'):
                parts = line.split(', ')
                if len(parts) >= 4:
                    gpus.append({
                        "name": parts[0].strip(),
                        "memory_total_gb": float(parts[1]) / 1024,
                        "memory_used_gb": float(parts[2]) / 1024,
                        "utilization_percent": float(parts[3])
                    })
            return gpus
    except:
        pass
    return []

@app.route('/api/avatar/control', methods=['POST'])
def avatar_control():
    """虚拟形象控制API - 通过Windows API控制运行中的PyQt5虚拟形象"""
    data = request.get_json()
    action = data.get('action', '')
    
    if sys.platform != 'win32':
        return jsonify({"status": "error", "message": "仅Windows平台支持此功能"})
    
    try:
        import ctypes
        from ctypes import wintypes
        
        user32 = ctypes.windll.user32
        
        # 自动查找虚拟形象窗口
        def find_avatar_window():
            """查找虚拟形象窗口句柄"""
            # 优先使用保存的PID查找
            global avatar_process
            if avatar_process and avatar_process.poll() is None:
                pid = avatar_process.pid
                # 通过进程ID查找窗口
                result = []
                def enum_callback(hwnd, _):
                    if user32.IsWindowVisible(hwnd):
                        window_pid = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                        if window_pid.value == pid:
                            result.append(hwnd)
                    return True
                
                WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
                if result:
                    return result[0]
            
            # 通过窗口标题查找
            hwnd = user32.FindWindowW(None, "元亨桌宠")
            if hwnd:
                return hwnd
            
            # 尝试查找子窗口
            result = []
            def enum_child_callback(hwnd, _):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if "元亨" in buf.value or "桌宠" in buf.value:
                        result.append(hwnd)
                return True
            
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_child_callback), 0)
            return result[0] if result else None
        
        hwnd = find_avatar_window()
        
        if not hwnd:
            return jsonify({"status": "error", "message": "虚拟形象未运行或窗口未找到"})
        
        # 窗口操作
        SW_SHOW = 5
        SW_HIDE = 0
        SW_RESTORE = 9
        SW_MINIMIZE = 6
        
        if action == 'show':
            user32.ShowWindow(hwnd, SW_SHOW)
            user32.SetForegroundWindow(hwnd)
            return jsonify({"success": True, "message": "窗口已显示"})
        
        elif action == 'hide':
            user32.ShowWindow(hwnd, SW_HIDE)
            return jsonify({"success": True, "message": "窗口已隐藏"})
        
        elif action == 'toggle':
            is_visible = user32.IsWindowVisible(hwnd)
            if is_visible:
                user32.ShowWindow(hwnd, SW_HIDE)
                return jsonify({"success": True, "message": "窗口已隐藏"})
            else:
                user32.ShowWindow(hwnd, SW_SHOW)
                user32.SetForegroundWindow(hwnd)
                return jsonify({"success": True, "message": "窗口已显示"})
        
        elif action == 'status':
            is_visible = user32.IsWindowVisible(hwnd)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            return jsonify({
                "success": True,
                "hwnd": int(hwnd),
                "visible": bool(is_visible),
                "position": {"x": rect.left, "y": rect.top},
                "size": {"width": rect.right - rect.left, "height": rect.bottom - rect.top}
            })
        
        elif action == 'chat':
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            return jsonify({"success": True, "message": "对话窗口已激活"})
        
        elif action == 'lock':
            # 锁定/解锁窗口（简化版：禁用/启用移动）
            return jsonify({"success": True, "message": "锁定功能已切换"})
        
        elif action == 'fade_in':
            user32.ShowWindow(hwnd, SW_SHOW)
            return jsonify({"success": True, "message": "淡入效果已触发"})
        
        elif action == 'fade_out':
            user32.ShowWindow(hwnd, SW_HIDE)
            return jsonify({"success": True, "message": "淡出效果已触发"})
        
        elif action == 'speak':
            return jsonify({"success": True, "message": "说话动画已触发"})
        
        elif action == 'bounce':
            return jsonify({"success": True, "message": "弹跳动画已触发"})
        
        elif action == 'move':
            x = data.get('x', 100)
            y = data.get('y', 100)
            user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001)  # SWP_NOSIZE
            return jsonify({"success": True, "message": f"已移动到 {x},{y}"})
        
        elif action == 'set_topmost':
            topmost = data.get('topmost', True)
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            hwnd_insert_after = HWND_TOPMOST if topmost else HWND_NOTOPMOST
            user32.SetWindowPos(hwnd, hwnd_insert_after, 0, 0, 0, 0, 0x0001 | 0x0002)
            return jsonify({"success": True, "message": f"置顶已{'开启' if topmost else '关闭'}"})
        
        else:
            return jsonify({"status": "error", "message": f"未知操作: {action}"}), 404
            
    except Exception as e:
        logger.error(f"虚拟形象控制失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/benchmark/pcm', methods=['POST'])
def run_pcm_benchmark():
    """运行PCM延迟测试"""
    data = request.get_json()
    test_type = data.get('type', 'all')
    iterations = data.get('iterations', 5)
    api_url = data.get('api_url', 'http://localhost:8000')
    
    try:
        from pcm_latency_test import PCMLatencyTester
        
        tester = PCMLatencyTester(api_url)
        
        if not tester.check_api_health():
            return jsonify({"status": "error", "message": "API服务不可用"})
        
        if test_type == 'llm':
            metric = tester.test_llm_first_token(iterations=iterations)
            return jsonify({"status": "success", "results": metric.summary()})
        elif test_type == 'tts_first':
            metric = tester.test_tts_first_pcm(iterations=iterations)
            return jsonify({"status": "success", "results": metric.summary()})
        elif test_type == 'tts_last':
            metric = tester.test_tts_last_pcm(iterations=iterations)
            return jsonify({"status": "success", "results": metric.summary()})
        elif test_type == 'total':
            metric = tester.test_total_roundtrip(iterations=iterations)
            return jsonify({"status": "success", "results": metric.summary()})
        elif test_type == 'all':
            report = tester.run_full_test()
            return jsonify({"status": "success", "results": report})
        else:
            return jsonify({"status": "error", "message": f"未知测试类型: {test_type}"}), 404
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/tech/comparison')
def get_tech_comparison():
    """获取技术比对分析"""
    try:
        from tech_comparison import get_full_comparison, generate_improvement_suggestions
        
        report = get_full_comparison()
        suggestions = generate_improvement_suggestions()
        
        return jsonify({
            "status": "success",
            "report": report,
            "suggestions": suggestions
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/services/<service_name>/restart', methods=['POST'])
def restart_service(service_name):
    """重启服务"""
    try:
        stop_service(service_name)
        time.sleep(1)
        start_service(service_name)
        return jsonify({"success": True, "message": f"{service_name}服务已重启"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    """清除日志文件"""
    try:
        if log_file.exists():
            with open(log_file, 'w') as f:
                f.write('')
        logger.info("日志已清除")
        return jsonify({"success": True, "message": "日志已清除"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/avatar/open_live2d', methods=['POST'])
def open_live2d_window():
    """打开Live2D查看器窗口"""
    try:
        import webbrowser
        # 优先使用 avatar 内嵌的 Live2D 服务器（端口 18765）
        if is_port_in_use(18765):
            webbrowser.open('http://localhost:18765/live2d_viewer.html')
            return jsonify({"success": True, "message": "已在浏览器中打开Live2D查看器"})
        elif is_port_in_use(8081):
            webbrowser.open('http://localhost:8081/live2d_viewer.html')
            return jsonify({"success": True, "message": "已在浏览器中打开Live2D查看器"})
        else:
            return jsonify({"success": False, "message": "Live2D服务未启动，请先启动虚拟形象"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    global backend_process, live2d_process, avatar_process
    stop_service('avatar')
    stop_service('live2d')
    stop_service('backend')
    logger.info("WebUI服务关闭中...")
    threading.Thread(target=lambda: time.sleep(1) and os._exit(0)).start()
    return jsonify({"success": True, "message": "服务正在关闭"})

@app.route('/api/memory/list')
def api_memory_list():
    """代理后端：获取所有记忆"""
    try:
        import requests as req
        resp = req.get('http://localhost:8000/memory/list', timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"memories": [], "error": str(e)}), 500

@app.route('/api/memory/add', methods=['POST'])
def api_memory_add():
    """代理后端：添加记忆"""
    data = request.get_json()
    try:
        import requests as req
        resp = req.post('http://localhost:8000/memory',
                        json={"content": data.get('content', ''), "importance": data.get('importance', 2)},
                        timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/memory/delete/<int:memory_id>', methods=['DELETE'])
def api_memory_delete(memory_id):
    """代理后端：删除记忆"""
    try:
        import requests as req
        resp = req.delete(f'http://localhost:8000/memory/{memory_id}', timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/personality', methods=['GET', 'POST'])
def api_personality():
    """代理后端：获取/更新角色设定"""
    try:
        import requests as req
        if request.method == 'GET':
            resp = req.get('http://localhost:8000/personality', timeout=10)
        else:
            data = request.get_json()
            resp = req.post('http://localhost:8000/personality',
                            json={"description": data.get('description', '')},
                            timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/tools/list')
def api_tools_list():
    """代理后端：获取工具列表"""
    try:
        import requests as req
        resp = req.get('http://localhost:8000/tools', timeout=10)
        data = resp.json()
        return jsonify(data)
    except Exception as e:
        return jsonify({"tools": [], "error": str(e)}), 500

@app.route('/api/tools/call', methods=['POST'])
def api_tools_call():
    """代理后端：调用工具"""
    data = request.get_json()
    try:
        import requests as req
        resp = req.post('http://localhost:8000/tools/call',
                        json={
                            "mode": data.get('mode', 'manual'),
                            "tool_name": data.get('tool_name', ''),
                            "parameters": data.get('parameters', {})
                        },
                        timeout=60)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/vision/<path:endpoint>', methods=['GET', 'POST'])
def api_vision_proxy(endpoint):
    """代理后端：视觉功能"""
    try:
        import requests as req
        url = f'http://localhost:8000/vision/{endpoint}'
        if request.method == 'GET':
            resp = req.get(url, timeout=10)
        else:
            resp = req.post(url, json=request.get_json() or {}, timeout=30)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/live2d/<path:endpoint>', methods=['GET', 'POST'])
def api_live2d_proxy(endpoint):
    """代理 Live2D 控制请求到后端 API (8000)"""
    try:
        import requests as req
        
        if not is_port_in_use(8000):
            return jsonify({"success": False, "message": "后端服务未启动，无法控制Live2D"}), 503
        
        url = f'http://localhost:8000/live2d/{endpoint}'
        if request.method == 'GET':
            resp = req.get(url, timeout=10)
        else:
            resp = req.post(url, json=request.get_json() or {}, timeout=15)
        return jsonify(resp.json())
    except req.ConnectionError:
        return jsonify({"success": False, "message": "后端服务连接失败"}), 503
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/tts/synthesize', methods=['POST'])
def api_tts_synthesize():
    """代理后端：语音合成"""
    data = request.get_json()
    try:
        import requests as req
        resp = req.post('http://localhost:8000/synthesize',
                        json={
                            "text": data.get('text', ''),
                            "voice": data.get('voice', 'Vivian'),
                            "rate": data.get('rate', '0%')
                        },
                        timeout=60)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/asr/transcribe', methods=['POST'])
def api_asr_transcribe():
    """代理后端：语音识别"""
    data = request.get_json()
    try:
        import requests as req
        resp = req.post('http://localhost:8000/transcribe',
                        json={
                            "audio_data": data.get('audio_data', []),
                            "sample_rate": data.get('sample_rate', 16000)
                        },
                        timeout=30)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"success": False, "text": "", "message": str(e)}), 500

@app.route('/api/chat/stream', methods=['POST'])
def api_chat_stream():
    """代理后端：SSE流式对话"""
    data = request.get_json()
    def proxy_stream():
        import requests as req
        try:
            upstream = req.post('http://localhost:8000/chat',
                                json={
                                    "text": data.get('message', ''),
                                    "tts_enabled": data.get('tts_enabled', False),
                                    "use_tools": data.get('use_tools', True)
                                },
                                stream=True, timeout=120)
            for line in upstream.iter_lines():
                if line:
                    yield line.decode('utf-8') + '\n\n'
        except Exception as e:
            yield f"data: {json.dumps({'content': '', 'is_done': True, 'full_content': f'连接失败: {str(e)}'}, ensure_ascii=False)}\n\n"
    return Response(proxy_stream(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache'})

@app.route('/api/config/save', methods=['POST'])
def api_config_save():
    """保存前端配置到 webui_config.json"""
    data = request.get_json()
    try:
        cfg = {}
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            except:
                cfg = {}
        cfg['settings'] = data
        cfg['last_updated'] = datetime.now().isoformat()
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        logger.info(f"配置已保存: {list(data.keys()) if isinstance(data, dict) else 'unknown'}")
        return jsonify({"success": True, "message": "配置已保存"})
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('webui_static', path)

def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def kill_port_process(port: int):
    """终止占用指定端口的进程"""
    try:
        for conn in psutil.net_connections():
            if conn.laddr.port == port and conn.status == 'LISTEN':
                try:
                    proc = psutil.Process(conn.pid)
                    proc.terminate()
                    proc.wait(timeout=5)
                    logger.info(f"已终止端口 {port} 的进程 PID:{conn.pid}")
                except Exception as e:
                    logger.warning(f"终止端口 {port} 进程失败: {e}")
    except Exception as e:
        logger.warning(f"检查端口 {port} 失败: {e}")

def save_webui_config():
    """保存WebUI配置"""
    config_data = {
        "last_position": services_status.get("last_position", {}),
        "theme": "dark",
        "auto_open_browser": True,
        "last_closed": datetime.now().isoformat()
    }
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

def cleanup_on_exit():
    """退出时清理"""
    global backend_process, live2d_process, avatar_process, avatar_status
    
    logger.info("=" * 60)
    logger.info("正在关闭服务...")
    logger.info("=" * 60)
    
    # 停止虚拟形象
    if avatar_process and avatar_process.poll() is None:
        logger.info("正在停止虚拟形象...")
        avatar_process.terminate()
        try:
            avatar_process.wait(timeout=5)
        except:
            avatar_process.kill()
        avatar_process = None
        avatar_status['running'] = False
        avatar_status['pid'] = None
        logger.info("虚拟形象已停止")
    
    # 停止后端服务
    if backend_process and backend_process.poll() is None:
        logger.info("正在停止后端服务...")
        backend_process.terminate()
        try:
            backend_process.wait(timeout=5)
        except:
            backend_process.kill()
        logger.info("后端服务已停止")
    
    # 停止Live2D服务
    if live2d_process and live2d_process.poll() is None:
        logger.info("正在停止Live2D服务...")
        live2d_process.terminate()
        try:
            live2d_process.wait(timeout=5)
        except:
            live2d_process.kill()
        logger.info("Live2D服务已停止")
    
    # 释放端口
    for port in [5000, 8000, 8081]:
        kill_port_process(port)
    
    # 保存配置
    save_webui_config()
    
    logger.info("所有服务已关闭，端口已释放")
    print("\n" + "=" * 60)
    print("  元亨 YHLZ 2.0 已安全关闭")
    print("  端口已释放，配置已保存")
    print("=" * 60)

def signal_handler(signum, frame):
    """信号处理器"""
    logger.info(f"收到信号 {signum}，准备退出...")
    cleanup_on_exit()
    os._exit(0)

def main():
    port = int(os.environ.get('WEBUI_PORT', 5000))
    host = os.environ.get('WEBUI_HOST', '127.0.0.1')
    
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup_on_exit)
    
    # 检查端口占用
    if is_port_in_use(port):
        print(f"\n[警告] 端口 {port} 已被占用，尝试释放...")
        kill_port_process(port)
        time.sleep(1)
        
        if is_port_in_use(port):
            print(f"[错误] 无法释放端口 {port}，请手动关闭占用进程")
            sys.exit(1)
    
    # 创建必要目录
    for d in ['logs', 'webui_templates', 'webui_static']:
        Path(d).mkdir(exist_ok=True)
    
    logger.info(f"=" * 60)
    logger.info(f"YHLZ 2.0 WebUI 启动")
    logger.info(f"地址: http://{host}:{port}")
    logger.info(f"日志: {log_file}")
    logger.info(f"=" * 60)
    
    print(f"\n{'='*60}")
    print(f"  YHLZ 2.0 元亨 WebUI")
    print(f"  访问地址: http://{host}:{port}")
    print(f"  按 Ctrl+C 停止服务")
    print(f"{'='*60}\n")
    
    # 自动打开浏览器
    auto_open = os.environ.get('WEBUI_AUTO_OPEN', 'true').lower() == 'true'
    if auto_open:
        def open_browser():
            time.sleep(1.5)  # 等待服务器启动
            url = f"http://{host}:{port}"
            logger.info(f"自动打开浏览器: {url}")
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()
    
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        cleanup_on_exit()

if __name__ == '__main__':
    main()
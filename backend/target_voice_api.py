"""Loopback-only controls for the opt-in daemon Target graph."""
import ipaddress
from urllib.parse import urlsplit

MAX_BODY_BYTES = 3 * 1024 * 1024

def local_request(handler):
    try:
        if not ipaddress.ip_address(handler.client_address[0]).is_loopback:
            return False
    except ValueError:
        return False
    origin = handler.headers.get('Origin')
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        if parsed.scheme not in {'http','https'} or parsed.hostname not in {'127.0.0.1','localhost','::1'}:
            return False
    return True


def handle_post(handler, payload):
    from backend.voice_jobs import VoiceJobError
    if not local_request(handler):
        handler._send(403, {'error':'VOICE-LOCAL-ONLY'})
        return
    if (handler.headers.get('Content-Type','').split(';',1)[0].strip().lower() != 'application/json'
            or not isinstance(payload, dict)):
        handler._send(400, {'error':'VOICE-JSON-REQUIRED'})
        return
    if payload.get('source') != 'console' or payload.get('channel','console') != 'console':
        handler._send(403, {'error':'VOICE-CONSOLE-ONLY'})
        return
    runtime = handler.runtime
    try:
        if handler.path == '/voice/start':
            service = runtime._ensure_target_voice()
            if service is None:
                handler._send(409, {'error':'VOICE-NOT-ENABLED-OR-READY'})
            else:
                health = service.health()
                handler._send(200 if health.get('ready') else 409, health)
        elif handler.path == '/voice/submit':
            audio = payload.get('audio')
            text = payload.get('text','')
            if (not isinstance(audio,list) or not 1 <= len(audio) <= 2
                    or any(not isinstance(a,str) or not a for a in audio)
                    or not isinstance(text,str) or len(text)>4000):
                handler._send(400, {'error':'VOICE-INVALID-INPUT'})
                return
            service = runtime._target_voice
            if service is None or not service.health().get('ready'):
                handler._send(409, {'error':'VOICE-START-REQUIRED'})
                return
            handler._send(202, runtime._voice_jobs.submit(runtime._loop, service, audio, text=text))
        elif handler.path == '/voice/cancel':
            job_id = payload.get('job_id')
            if not isinstance(job_id,str):
                handler._send(400, {'error':'VOICE-JOB-ID-REQUIRED'})
                return
            handler._send(202, runtime._voice_jobs.cancel(runtime._loop, job_id))
        else:
            handler._send(404, {'error':'not found'})
    except KeyError:
        handler._send(404, {'error':'VOICE-JOB-NOT-FOUND'})
    except VoiceJobError as exc:
        handler._send(429, {'error':str(exc)})
    except Exception as exc:
        handler._send(500, {'error':type(exc).__name__})


def handle_get(handler):
    if not local_request(handler):
        handler._send(403, {'error':'VOICE-LOCAL-ONLY'})
        return
    job_id = handler.path.removeprefix('/voice/jobs/').split('?',1)[0]
    try:
        handler._send(200, handler.runtime._voice_jobs.get(job_id))
    except KeyError:
        handler._send(404, {'error':'VOICE-JOB-NOT-FOUND'})

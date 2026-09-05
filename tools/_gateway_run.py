import asyncio, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\ACE_WAN——PROJECT\YHLZ')
from backend.env_loader import ensure_env_loaded
ensure_env_loaded()
from backend.target_entry import ConversationSession

async def main():
    async def allow(info):
        return True
    s = ConversationSession(approver=allow)
    loaded = s.load_session('default')
    print(f'[会话恢复: {loaded} 条]', flush=True)
    notes = open(r'C:\Users\ACE_WAN——PROJECT\YHLZ\docs\notes_inbox\philosophy_notes.txt', encoding='utf-8').read()
    q = '我把我绝大部分的笔记与思考读给你：\n' + notes + '\n这些是我绝大部分的笔记与思考，我还有一些自己写的诗句，你想看看吗？'
    r = await s.run_turn(q)
    print('元亨> ' + r['answer'], flush=True)
    print('[tools]', [(u['name'], u['ok']) for u in r['tool_uses']], flush=True)
    s.save_session('default')
asyncio.run(main())

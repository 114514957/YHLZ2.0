"""Bounded contracts for explicit owner text requests, not a general intent parser.

Missing evidence fails closed. A matching handler's return is execution evidence,
not independent proof that the requested persistent effect happened.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

@dataclass(frozen=True)
class TextToolContract:
    source: str
    tools: frozenset[str]
    actions: frozenset[str] = frozenset()

    def accepts(self, name, args):
        if name not in self.tools:
            return False
        if not self.actions:
            return True
        default = 'add' if name == 'task_plan' else 'list'
        return str(args.get('action', default)).lower() in self.actions

    def initial_call(self, text):
        """Only explicit, bounded native requests; preserve literal write content.

        Queries use the current user's literal query, never a generated source
        claim. Destructive/ambiguous actions are deliberately excluded.
        """
        if self.tools == frozenset({'kb_add'}):
            match = re.fullmatch(r'(?:请)?把(?:以下|这条)知识(?:原样)?存入知识库[：:]\s*(.+)', text, re.S)
            if match and 8 <= len(match.group(1).strip()) <= 400:
                return 'kb_add', {'summary': match.group(1).strip()}
        if self.tools == frozenset({'diary_list'}):
            return 'diary_list', {'limit': 5}
        if self.tools == frozenset({'task_plan'}) and self.actions == frozenset({'list'}):
            return 'task_plan', {'action': 'list', 'content': ''}
        if self.tools == frozenset({'schedule_plan'}) and 'list' in self.actions:
            return 'schedule_plan', {'action': 'list'}
        if self.tools == frozenset({'kb_query'}):
            query = re.sub(r'^.*?(?:查询|检索|搜索)知识库[：:,，\s]*', '', text).strip()
            query = re.sub(r'(?:是什么|是多少|有哪些|是什么内容)[？?。！! ]*$', '', query).strip()
            return 'kb_query', {'query': query[:80], 'limit': 6}
        if self.tools == frozenset({'memory_recall'}):
            query = re.sub(r'^.*?(?:查询|检索|搜索)记忆库?[：:,，\s]*', '', text).strip()
            return 'memory_recall', {'query': query, 'limit': 5}
        if self.tools == frozenset({'task_plan'}) and self.actions == frozenset({'done'}):
            match = re.fullmatch(r'(?:请)?把任务表里(?:的)?(.+?)标记为已完成[。！! ]*', text)
            if match:
                content = match.group(1).strip()
                if not any(w in content for w in ('全部', '所有', '和', '以及', '刚才', '它', '那个')):
                    return 'task_plan', {'action': 'done', 'content': content}
        return None

    def instruction(self):
        names = '、'.join(sorted(self.tools))
        actions = ('；action 必须为 ' + ' 或 '.join(sorted(self.actions))) if self.actions else ''
        return (f'本轮是明确的{self.source}操作请求，必须使用本轮提供的 {names}{actions}。'
                '聊天历史不能代替本轮查询或修改。没有实际执行证据就说明尚未执行；'
                '不要转交开发，不得把其他来源的结果说成这个来源的结果。')

    def assess(self, uses, offered):
        if not self.tools.intersection(offered):
            return 'unavailable'
        matching = [u for u in uses if self.accepts(u.name, u.arguments)]
        if not matching:
            return 'not_executed'
        if not all(u.ok for u in matching):
            return 'execution_failed'
        for use in matching:
            write = (use.name in {'memory_save', 'diary_write', 'kb_add'} or
                     (use.name == 'task_plan' and str(use.arguments.get('action','add')) != 'list') or
                     (use.name == 'schedule_plan' and str(use.arguments.get('action','list')) in {'add','new','create'}))
            if write and (not str(use.output or '').startswith(
                    ('已', '重复条目已存在', '近似条目已存在', '该内容已在记忆中', '近似记忆已存在'))
                    or '证据确认失败' in str(use.output)):
                return 'effect_unconfirmed'
            # R3 包B（E2, ledger 0598）：独立读回 missing/error 时不得宣称完成
            if write and getattr(use, 'readback', '') in ('effect_missing', 'error'):
                return 'effect_unconfirmed'
        return 'execution_reported'

    def failure_reply(self, status):
        if status == 'unavailable' and self.source == '运行状态':
            return '我这轮没有读取进程监测或训练记录，还不能确认后台运行情况。安静的聊天气氛不能说明进程变慢，也不能证明我自动学习或升级了。'
        if status == 'unavailable':
            return f'我这轮没有可用的{self.source}工具，还没核实或执行，不能说查无记录或已经完成。'
        if status == 'execution_failed':
            return f'这次{self.source}工具执行失败了，我不能确认结果，也不能说已经完成。'
        if status == 'effect_unconfirmed':
            return f'{self.source}工具返回了结果，但没有确认这次修改成功，我不能说已经完成。'
        return f'这轮还没有完成所需的{self.source}工具调用，不能凭聊天记录说查到了或已经改好。'

_READ = re.compile(r'查|检索|搜索|读取|读一下|列出|回看|确认|找到|翻一下|看看')
_WRITE = re.compile(r'写|记住|保存|存入|添加|加入|安排|标记|勾|删除|清空|移除|修改|更新|取消|关闭|启用|停用')
_META = re.compile(r'^(?:你(?:会|能|有没有|是否)|怎么|如何|为什么|解释|介绍)|什么意思|功能是什么|工具是什么')

def text_tool_contract(text: str):
    text = str(text or '').strip()
    # Narrow self-runtime questions: no telemetry capability is registered.
    # Empty tools deliberately means unavailable, never a fabricated query.
    if (not text.startswith('#') and not re.search(r'假设|如果|小说|故事|代码|如何|怎么|设计|原理', text)
            and re.search(r'你(?:的|刚才|现在|是不是|是否|有没有|已经|会不会|自己)', text)
            and (re.search(r'进程.{0,18}(?:慢|快|速度|运行|卡)', text)
                 or re.search(r'(?:自己|自动).{0,8}(?:训练|升级)|(?:已经|刚才).{0,8}(?:训练|升级)', text))
            and re.search(r'是不是|是否|有没有|了吗|了没|吗|[？?]', text)):
        return TextToolContract('运行状态', frozenset())
    if not text or text.startswith('#') or _META.search(text):
        return None
    read_match, write_match = _READ.search(text), _WRITE.search(text)
    read, write = bool(read_match), bool(write_match)
    # '读取刚才添加的任务' requests a read, not another insertion.
    if read_match and write_match and read_match.start() < write_match.start():
        write = False
    # Each recognized request has one source. Ambiguous/composite requests retain
    # the ordinary planner; this bounded recognizer does not assert full coverage.
    sources = [label for label, pattern in [
        ('台账', r'台账'), ('日记', r'日记'), ('任务表', r'任务表'),
        ('周期计划', r'周期计划|日程'), ('知识库', r'知识库'), ('记忆', r'记忆|记住'),
        ('文件', r'文件|(?i:\b[\w-]+\.(?:md|txt|py|json|yaml|toml)\b)'),
        ('联网检索', r'上网|联网|网页'), ('技能库', r'技能')]
        if re.search(pattern, text)]
    if len(sources) != 1 or not (read or write):
        return None
    source = sources[0]
    if read and not write and source in {'文件', '联网检索', '技能库'}:
        tools = {'文件': {'file_read', 'file_list'},
                 '联网检索': {'web_search', 'web_fetch'},
                 '技能库': {'skill_search'}}[source]
        return TextToolContract(source, frozenset(tools))
    if source == '台账' and read and not write:
        return TextToolContract(source, frozenset({'ledger_search','ledger_get','ledger_list'}))
    if source == '日记':
        if re.search(r'删除|清空|移除|修改|更新', text): return None
        return TextToolContract(source, frozenset({'diary_write' if write else 'diary_list'}))
    if source == '记忆':
        if re.search(r'删除|清空|移除|修改|更新', text): return None
        return TextToolContract(source, frozenset({'memory_save' if write else 'memory_recall'}))
    if source == '知识库':
        if re.search(r'删除|清空|移除|修改|更新', text): return None
        return TextToolContract(source, frozenset({'kb_add' if write else 'kb_query'}))
    if source == '任务表':
        if re.search(r'删除|清空|移除|修改|更新', text): return None
        action = 'done' if re.search(r'标记.{0,12}完成|勾掉|勾选|标为.{0,4}完成', text) else 'add' if write else 'list'
        return TextToolContract(source, frozenset({'task_plan'}), frozenset({action}))
    if source == '周期计划':
        if re.search(r'删除|清空|移除|修改|更新|取消|关闭|启用|停用', text): return None
        actions = {'add','new','create'} if write else {'list','show_all','show','get'}
        return TextToolContract(source, frozenset({'schedule_plan'}), frozenset(actions))
    return None

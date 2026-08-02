from backend.plugin_sdk import NekoPluginBase, neko_plugin, plugin_entry, Ok, Err
from datetime import datetime
import re
import threading
import time


@neko_plugin
class UtilityToolsPlugin(NekoPluginBase):

    @plugin_entry(
        id="calculator",
        name="计算器",
        description="执行数学运算",
        metadata={"category": "utility"},
        parameters={"expression": {"type": "str", "description": "数学表达式，如 \"2 + 3 * 4\""}}
    )
    def calculator(self, expression: str = "0", **_):
        allowed_pattern = re.compile(r'^[\d\s+\-*/().%^]+$')

        if not allowed_pattern.match(expression):
            return Err(f"表达式包含非法字符: {expression}")

        try:
            result = eval(expression)
            return Ok({"result": f"计算结果: {expression} = {result}"})
        except Exception as e:
            return Err(f"计算错误: {e}")

    @plugin_entry(
        id="get_time",
        name="获取当前时间",
        description="获取当前日期和时间",
        metadata={"category": "utility"}
    )
    def get_time(self, **_):
        now = datetime.now()
        return Ok({"result": f"当前时间: {now.strftime('%Y年%m月%d日 %H:%M:%S')}"})

    @plugin_entry(
        id="get_date",
        name="获取当前日期",
        description="获取当前日期和星期",
        metadata={"category": "utility"}
    )
    def get_date(self, **_):
        today = datetime.now().date()
        week_day = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][today.weekday()]
        return Ok({"result": f"当前日期: {today.strftime('%Y年%m月%d日')} {week_day}"})

    @plugin_entry(
        id="set_reminder",
        name="设置提醒",
        description="设置一个定时提醒",
        metadata={"category": "utility"},
        parameters={
            "message": {"type": "str", "description": "提醒消息内容"},
            "minutes": {"type": "int", "description": "多少分钟后提醒（默认5分钟）"}
        }
    )
    def set_reminder(self, message: str = "", minutes: int = 5, **_):
        if not message:
            return Err("提醒消息不能为空")

        def remind():
            time.sleep(minutes * 60)
            self.logger.info(f"⏰ 提醒: {message}")
            asyncio.run(self.push_message(message_type="text", content=f"⏰ 提醒: {message}", priority=5))

        thread = threading.Thread(target=remind, daemon=True)
        thread.start()

        return Ok({"result": f"已设置提醒，{minutes}分钟后提醒: {message}"})
import asyncio
import logging
import time
from enum import Enum
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger(__name__)


class LiveStatus(Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    LIVE = "live"
    BREAK = "break"
    ENDING = "ending"
    ENDED = "ended"


class StreamStats:
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.danmaku_count = 0
        self.gift_count = 0
        self.gift_value = 0
        self.viewer_count = 0
        self.peak_viewers = 0
        self.response_count = 0
        self.topic_count = 0
        self.energy_level = 100
        self.interaction_rate = 0.0
        
    @property
    def duration(self):
        if not self.start_time:
            return 0
        end = self.end_time or time.time()
        return int(end - self.start_time)
    
    def update_interaction_rate(self):
        if self.duration > 0 and self.danmaku_count > 0:
            self.interaction_rate = self.response_count / max(1, self.danmaku_count)


class LiveStreamManager:
    
    def __init__(self):
        self.status = LiveStatus.IDLE
        self.stats = StreamStats()
        
        self.bilibili_plugin = None
        self.vtube_plugin = None
        self.mouth_sync_engine = None
        self.expression_controller = None
        self.topic_generator = None
        self.chat_flow_controller = None
        
        self._danmaku_buffer = []
        self._gift_buffer = []
        self._response_queue = asyncio.Queue()
        self._running = False
        
        self._last_danmaku_time = 0
        self._last_response_time = 0
        self._last_topic_time = 0
        self._last_break_time = 0
        
        self._cold_detection_threshold = 30
        self._topic_interval = 300
        self._break_interval = 1800
        self._break_duration = 300
        
        self._energy_decay_rate = 0.005
        self._energy_recovery_rate = 0.02
        
        self._max_danmaku_history = 200
        self._response_delay = 2
        
        self._llm_engine = None
        self._memory_manager = None
        
        self._on_status_change = None
        self._on_stats_update = None

    def set_plugins(self, bilibili_plugin=None, vtube_plugin=None):
        self.bilibili_plugin = bilibili_plugin
        self.vtube_plugin = vtube_plugin
        
        if self.bilibili_plugin:
            self.bilibili_plugin.set_danmaku_callback(self._on_danmaku)
            self.bilibili_plugin.set_gift_callback(self._on_gift)

    def set_engines(self, mouth_sync=None, expression_ctrl=None, topic_gen=None, chat_flow=None, cognitive_engine=None, cognitive_avatar_controller=None):
        self.mouth_sync_engine = mouth_sync
        self.expression_controller = expression_ctrl
        self.topic_generator = topic_gen
        self.chat_flow_controller = chat_flow
        self._cognitive_engine = cognitive_engine
        self._cognitive_avatar_controller = cognitive_avatar_controller
        
        if self._cognitive_avatar_controller and self.vtube_plugin:
            self._cognitive_avatar_controller.set_plugins(
                vtube_plugin=self.vtube_plugin,
                cognitive_engine=cognitive_engine,
                expression_controller=expression_ctrl
            )

    def set_callbacks(self, on_status_change=None, on_stats_update=None):
        self._on_status_change = on_status_change
        self._on_stats_update = on_stats_update

    async def start_stream(self, room_id: int, cookies: Dict[str, str] = None):
        if self.status != LiveStatus.IDLE:
            return {"error": "当前状态不允许启动"}
        
        self.status = LiveStatus.PREPARING
        
        try:
            if self.bilibili_plugin:
                result = await self.bilibili_plugin.connect_room(room_id=room_id, **(cookies or {}))
                if hasattr(result, 'error'):
                    return {"error": str(result.error)}
            
            if self.vtube_plugin:
                result = await self.vtube_plugin.connect()
                if hasattr(result, 'error'):
                    return {"error": str(result.error)}
            
            self.stats.start_time = time.time()
            self.status = LiveStatus.LIVE
            self._running = True
            
            await self._broadcast_status()
            await self._broadcast_stats()
            
            asyncio.create_task(self._main_loop())
            asyncio.create_task(self._response_worker())
            asyncio.create_task(self._energy_manager())
            asyncio.create_task(self._auto_topic_generator())
            
            if self._cognitive_avatar_controller:
                asyncio.create_task(self._cognitive_avatar_controller.start_processing())
            
            return {"success": True, "message": "直播已开始"}
            
        except Exception as e:
            logger.error(f"启动直播失败: {e}")
            self.status = LiveStatus.IDLE
            return {"error": str(e)}

    async def end_stream(self):
        if self.status not in [LiveStatus.LIVE, LiveStatus.BREAK]:
            return {"error": "当前没有正在进行的直播"}
        
        self.status = LiveStatus.ENDING
        await self._broadcast_status()
        
        try:
            await self._send_farewell_message()
            
            if self.bilibili_plugin:
                await self.bilibili_plugin.disconnect()
            
            if self.vtube_plugin:
                await self.vtube_plugin.disconnect()
            
            if self._cognitive_avatar_controller:
                await self._cognitive_avatar_controller.stop_processing()
            
            await self._save_live_memory()
            
            self.stats.end_time = time.time()
            self.status = LiveStatus.ENDED
            self._running = False
            
            await self._broadcast_status()
            await self._broadcast_stats()
            
            return {"success": True, "message": "直播已结束"}
            
        except Exception as e:
            logger.error(f"结束直播失败: {e}")
            return {"error": str(e)}

    async def take_break(self):
        if self.status != LiveStatus.LIVE:
            return {"error": "当前不是直播状态"}
        
        self.status = LiveStatus.BREAK
        self._last_break_time = time.time()
        
        await self._send_break_message()
        
        if self.vtube_plugin:
            await self.vtube_plugin.set_expression("neutral")
        
        await self._broadcast_status()
        
        return {"success": True, "message": "进入休息时间"}

    async def resume_stream(self):
        if self.status != LiveStatus.BREAK:
            return {"error": "当前不是休息状态"}
        
        self.status = LiveStatus.LIVE
        
        await self._send_resume_message()
        
        if self.vtube_plugin:
            await self.vtube_plugin.set_expression("happy")
        
        await self._broadcast_status()
        
        return {"success": True, "message": "直播已恢复"}

    async def send_message(self, content: str):
        if self.status not in [LiveStatus.LIVE, LiveStatus.BREAK]:
            return {"error": "当前没有正在进行的直播"}
        
        if not self.bilibili_plugin:
            return {"error": "B站插件未连接"}
        
        result = await self.bilibili_plugin.send_danmaku(content)
        
        if hasattr(result, 'error'):
            return {"error": str(result.error)}
        
        return {"success": True, "message": "消息发送成功"}

    async def set_expression(self, expression: str):
        if not self.vtube_plugin:
            return {"error": "VTube Studio插件未连接"}
        
        result = await self.vtube_plugin.set_expression(expression)
        
        if hasattr(result, 'error'):
            return {"error": str(result.error)}
        
        return {"success": True, "message": f"表情已设置为: {expression}"}

    async def _main_loop(self):
        while self._running:
            try:
                await self._check_cold_silence()
                await self._check_auto_break()
                
                if self.stats.duration > 0:
                    self.stats.update_interaction_rate()
                
                await self._broadcast_stats()
                
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                await asyncio.sleep(5)

    async def _response_worker(self):
        while self._running:
            try:
                item = await self._response_queue.get()
                
                await asyncio.sleep(self._response_delay)
                
                result = await self.bilibili_plugin.send_danmaku(item['response'])
                
                if hasattr(result, 'error'):
                    logger.error(f"回复发送失败: {result.error}")
                else:
                    self.stats.response_count += 1
                
                self._response_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"回复工作者异常: {e}")

    async def _energy_manager(self):
        while self._running:
            try:
                if self.status == LiveStatus.LIVE:
                    self.stats.energy_level = max(0, self.stats.energy_level - self._energy_decay_rate * 60)
                elif self.status == LiveStatus.BREAK:
                    self.stats.energy_level = min(100, self.stats.energy_level + self._energy_recovery_rate * 60)
                
                if self.stats.energy_level < 20 and self.status == LiveStatus.LIVE:
                    await self.take_break()
                
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"能量管理异常: {e}")

    async def _auto_topic_generator(self):
        while self._running:
            try:
                if self.status != LiveStatus.LIVE:
                    await asyncio.sleep(30)
                    continue
                
                now = time.time()
                if now - self._last_topic_time >= self._topic_interval:
                    topic = self._generate_topic()
                    
                    if topic:
                        await self.bilibili_plugin.send_danmaku(topic)
                        self.stats.topic_count += 1
                        self._last_topic_time = now
                        logger.info(f"自动生成话题: {topic}")
                
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"话题生成异常: {e}")

    async def _on_danmaku(self, danmaku):
        self._last_danmaku_time = time.time()
        self.stats.danmaku_count += 1
        
        self._danmaku_buffer.append(danmaku)
        if len(self._danmaku_buffer) > self._max_danmaku_history:
            self._danmaku_buffer = self._danmaku_buffer[-self._max_danmaku_history:]
        
        asyncio.create_task(self._process_danmaku(danmaku))

    async def _on_gift(self, gift):
        self.stats.gift_count += 1
        
        self._gift_buffer.append(gift)
        
        asyncio.create_task(self._process_gift(gift))

    async def _process_danmaku(self, danmaku):
        try:
            if self.status != LiveStatus.LIVE:
                return
            
            content = danmaku.get('content', '')
            user = danmaku.get('user', '')
            
            if self.expression_controller:
                expression = self.expression_controller.analyze_expression(content)
                if self.vtube_plugin:
                    await self.vtube_plugin.set_expression(expression)
            
            if len(content) > 5:
                response = await self._generate_response(content)
                
                if response:
                    await self._response_queue.put({
                        'danmaku': danmaku,
                        'response': response
                    })
            
        except Exception as e:
            logger.error(f"处理弹幕异常: {e}")

    async def _process_gift(self, gift):
        try:
            user = gift.get('user', '')
            gift_name = gift.get('gift', '')
            num = gift.get('num', 1)
            
            thank_msg = f"感谢 {user} 送的 {num} 个 {gift_name}！太感谢了！"
            
            await self.bilibili_plugin.send_danmaku(thank_msg)
            
            if self.vtube_plugin:
                await self.vtube_plugin.set_expression("happy")
                await asyncio.sleep(1)
                await self.vtube_plugin.set_expression("neutral")
            
        except Exception as e:
            logger.error(f"处理礼物异常: {e}")

    async def _generate_response(self, content):
        try:
            llm = self._get_llm_engine()
            
            context = [
                {"role": "system", "content": "你是一个B站虚拟主播，正在直播中。请用简短、活泼、亲切的语气回复弹幕。回复要简短，不超过30个字。"},
                {"role": "user", "content": content}
            ]
            
            response = await llm.generate_stream(context, temperature=0.8, flush_threshold=1)
            
            full_response = ""
            async for chunk in response:
                full_response += chunk
            
            return full_response.strip()[:30]
            
        except Exception as e:
            logger.error(f"生成回复异常: {e}")
            return None

    def _generate_topic(self):
        if not self.topic_generator:
            return None
        
        try:
            topic = self.topic_generator.generate_topic(self._danmaku_buffer)
            return topic
        except Exception as e:
            logger.error(f"生成话题异常: {e}")
            return None

    async def _check_cold_silence(self):
        if self.status != LiveStatus.LIVE:
            return
        
        now = time.time()
        if now - self._last_danmaku_time > self._cold_detection_threshold:
            topic = self._generate_topic()
            
            if topic:
                await self.bilibili_plugin.send_danmaku(topic)
                self.stats.topic_count += 1
                self._last_topic_time = now
                logger.info(f"检测到冷场，生成话题: {topic}")

    async def _check_auto_break(self):
        if self.status != LiveStatus.LIVE:
            return
        
        now = time.time()
        if now - self._last_break_time > self._break_interval:
            await self.take_break()

    async def _send_break_message(self):
        messages = [
            "稍微休息一下~",
            "喝口水，马上回来！",
            "休息一会儿，很快回来！",
            "稍等片刻，马上继续！"
        ]
        await self.bilibili_plugin.send_danmaku(messages[0])

    async def _send_resume_message(self):
        messages = [
            "回来啦！继续聊天！",
            "休息结束，继续！",
            "我回来啦！大家久等了！",
            "继续继续！"
        ]
        await self.bilibili_plugin.send_danmaku(messages[0])

    async def _send_farewell_message(self):
        messages = [
            "今天的直播就到这里啦，感谢大家的陪伴！",
            "拜拜~下次直播再见！",
            "谢谢大家今天的支持，明天见！",
            "下播啦，大家早点休息！"
        ]
        await self.bilibili_plugin.send_danmaku(messages[0])

    async def _save_live_memory(self):
        try:
            memory_manager = self._get_memory_manager()
            
            summary = f"直播记录: 时长{self.stats.duration}秒, 弹幕{self.stats.danmaku_count}条, 礼物{self.stats.gift_count}个"
            
            memory_manager.add_memory(
                content=summary,
                category="live",
                importance=3,
                context_tags=["直播", "记录"]
            )
            
            if len(self._danmaku_buffer) > 0:
                hot_topics = self._extract_hot_topics()
                if hot_topics:
                    memory_manager.add_memory(
                        content=f"热门话题: {', '.join(hot_topics)}",
                        category="live",
                        importance=4,
                        context_tags=["直播", "热门话题"]
                    )
            
            logger.info("直播记忆已保存")
            
        except Exception as e:
            logger.error(f"保存直播记忆失败: {e}")

    def _extract_hot_topics(self):
        if len(self._danmaku_buffer) < 10:
            return None
        
        word_counts = {}
        for danmaku in self._danmaku_buffer:
            content = danmaku.get('content', '')
            words = content.split()
            for word in words:
                if len(word) >= 2:
                    word_counts[word] = word_counts.get(word, 0) + 1
        
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_words[:5] if count >= 3]

    def _get_llm_engine(self):
        if self._llm_engine is None:
            try:
                from backend.llm_engine import llm_engine
                self._llm_engine = llm_engine
            except ImportError:
                logger.error("无法导入LLM引擎")
        return self._llm_engine

    def _get_memory_manager(self):
        if self._memory_manager is None:
            try:
                from backend.memory import MemoryManager
                self._memory_manager = MemoryManager()
            except ImportError:
                logger.error("无法导入记忆管理器")
        return self._memory_manager

    async def _broadcast_status(self):
        if self._on_status_change:
            try:
                await self._on_status_change(self.status.value)
            except:
                pass

    async def _broadcast_stats(self):
        if self._on_stats_update:
            try:
                await self._on_stats_update(self.get_stats())
            except:
                pass

    def get_stats(self):
        return {
            'status': self.status.value,
            'duration': self.stats.duration,
            'danmaku_count': self.stats.danmaku_count,
            'gift_count': self.stats.gift_count,
            'response_count': self.stats.response_count,
            'topic_count': self.stats.topic_count,
            'energy_level': self.stats.energy_level,
            'interaction_rate': self.stats.interaction_rate
        }

    def get_status(self):
        return self.status.value

    async def update_mouth_sync(self, audio_data):
        if not self.mouth_sync_engine or not self.vtube_plugin:
            return
        
        mouth_value = self.mouth_sync_engine.calculate_mouth_open(audio_data)
        
        if self.vtube_plugin.is_connected:
            await self.vtube_plugin.set_mouth_open(mouth_value)
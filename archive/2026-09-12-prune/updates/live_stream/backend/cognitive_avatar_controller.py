import asyncio
import logging
from typing import Dict, Any, Optional
from enum import Enum
import time

logger = logging.getLogger(__name__)


class CognitiveReactionType(Enum):
    NEUTRAL = "neutral"
    ALERT = "alert"
    FOCUSED = "focused"
    SURPRISED = "surprised"
    CALM = "calm"
    EXCITED = "excited"
    THREATENED = "threatened"
    BEAUTY_AWE = "beauty_awe"


class CognitiveAvatarController:
    
    def __init__(self):
        self._vtube_plugin = None
        self._cognitive_engine = None
        self._expression_controller = None
        
        self._last_reaction = CognitiveReactionType.NEUTRAL
        self._reaction_cooldown = 2.0
        self._last_reaction_time = 0
        
        self._attention_smoothing = []
        self._max_attention_history = 5
        
        self._cognitive_state_map = {
            "idle": CognitiveReactionType.NEUTRAL,
            "processing": CognitiveReactionType.FOCUSED,
            "high_tension": CognitiveReactionType.ALERT,
            "overload": CognitiveReactionType.THREATENED
        }
        
        self._tension_reaction_map = {
            "正常": CognitiveReactionType.NEUTRAL,
            "高张力(危机张力)": CognitiveReactionType.THREATENED,
            "高张力(美学张力)": CognitiveReactionType.BEAUTY_AWE
        }
        
        self._reaction_expression_map = {
            CognitiveReactionType.NEUTRAL: "neutral",
            CognitiveReactionType.ALERT: "surprised",
            CognitiveReactionType.FOCUSED: "confused",
            CognitiveReactionType.SURPRISED: "surprised",
            CognitiveReactionType.CALM: "neutral",
            CognitiveReactionType.EXCITED: "excited",
            CognitiveReactionType.THREATENED: "angry",
            CognitiveReactionType.BEAUTY_AWE: "surprised"
        }
        
        self._reaction_animation_map = {
            CognitiveReactionType.NEUTRAL: None,
            CognitiveReactionType.ALERT: "blink",
            CognitiveReactionType.FOCUSED: None,
            CognitiveReactionType.SURPRISED: "blink",
            CognitiveReactionType.CALM: None,
            CognitiveReactionType.EXCITED: "wave_hand",
            CognitiveReactionType.THREATENED: None,
            CognitiveReactionType.BEAUTY_AWE: "blink"
        }
        
        self._enabled = True
        self._processing_task = None

    def set_plugins(self, vtube_plugin=None, cognitive_engine=None, expression_controller=None):
        self._vtube_plugin = vtube_plugin
        self._cognitive_engine = cognitive_engine
        self._expression_controller = expression_controller

    async def start_processing(self):
        if self._processing_task:
            return
        
        self._processing_task = asyncio.create_task(self._processing_loop())
        logger.info("认知驱动虚拟形象控制器已启动")

    async def stop_processing(self):
        if self._processing_task:
            self._processing_task.cancel()
            self._processing_task = None
        logger.info("认知驱动虚拟形象控制器已停止")

    async def process_cognitive_output(self, cognitive_output):
        if not self._enabled:
            return
        
        if not self._vtube_plugin or not self._vtube_plugin.is_connected:
            return
        
        try:
            reaction = self._determine_reaction(cognitive_output)
            
            await self._apply_reaction(reaction, cognitive_output)
            
            await self._apply_attention(cognitive_output)
            
            await self._apply_cross_modal_effects(cognitive_output)
            
            self._last_reaction = reaction
            self._last_reaction_time = time.time()
            
        except Exception as e:
            logger.error(f"处理认知输出失败: {e}")

    def _determine_reaction(self, cognitive_output) -> CognitiveReactionType:
        system_state = cognitive_output.system_state
        
        reaction = self._cognitive_state_map.get(system_state, CognitiveReactionType.NEUTRAL)
        
        vision_tension = cognitive_output.vision.intuitive_tag
        audio_tension = cognitive_output.audio.intuitive_tag
        
        vision_reaction = self._tension_reaction_map.get(vision_tension, CognitiveReactionType.NEUTRAL)
        audio_reaction = self._tension_reaction_map.get(audio_tension, CognitiveReactionType.NEUTRAL)
        
        if vision_reaction == CognitiveReactionType.THREATENED or audio_reaction == CognitiveReactionType.THREATENED:
            return CognitiveReactionType.THREATENED
        
        if vision_reaction == CognitiveReactionType.BEAUTY_AWE or audio_reaction == CognitiveReactionType.BEAUTY_AWE:
            return CognitiveReactionType.BEAUTY_AWE
        
        if system_state == "high_tension":
            return CognitiveReactionType.ALERT
        
        if system_state == "processing" and cognitive_output.thinking.cognitive_bandwidth > 0.8:
            return CognitiveReactionType.FOCUSED
        
        return reaction

    async def _apply_reaction(self, reaction: CognitiveReactionType, cognitive_output):
        now = time.time()
        if now - self._last_reaction_time < self._reaction_cooldown:
            return
        
        expression = self._reaction_expression_map.get(reaction, "neutral")
        
        await self._vtube_plugin.set_expression(expression)
        
        animation = self._reaction_animation_map.get(reaction)
        if animation:
            if animation == "blink":
                await self._vtube_plugin.blink()
            elif animation == "wave_hand":
                await self._vtube_plugin.trigger_animation("wave_hand")

    async def _apply_attention(self, cognitive_output):
        attention = cognitive_output.thinking.cross_modal_fusion.get("attention_focus", {})
        
        vision_weight = attention.get("vision", 0.5)
        audio_weight = attention.get("audio", 0.5)
        
        self._attention_smoothing.append({"vision": vision_weight, "audio": audio_weight})
        if len(self._attention_smoothing) > self._max_attention_history:
            self._attention_smoothing.pop(0)
        
        avg_vision = sum(a["vision"] for a in self._attention_smoothing) / len(self._attention_smoothing)
        avg_audio = sum(a["audio"] for a in self._attention_smoothing) / len(self._attention_smoothing)
        
        head_x = (avg_vision - 0.5) * 0.4
        head_y = (avg_audio - 0.5) * 0.2
        
        await self._vtube_plugin.set_parameter_with_easing(
            "HeadX", head_x, duration=0.5, easing="easeBoth"
        )
        await self._vtube_plugin.set_parameter_with_easing(
            "HeadY", head_y, duration=0.5, easing="easeBoth"
        )

    async def _apply_cross_modal_effects(self, cognitive_output):
        patterns = cognitive_output.thinking.cross_modal_fusion.get("emergent_patterns", [])
        
        if "多模态共鸣" in patterns:
            await self._vtube_plugin.set_parameter_with_easing(
                "BodyAngle", 0.05, duration=0.3, easing="easeOut"
            )
            await asyncio.sleep(0.3)
            await self._vtube_plugin.set_parameter_with_easing(
                "BodyAngle", -0.05, duration=0.3, easing="easeBoth"
            )
            await asyncio.sleep(0.3)
            await self._vtube_plugin.set_parameter_with_easing(
                "BodyAngle", 0.0, duration=0.3, easing="easeOut"
            )
        
        if "空间感知激活" in patterns:
            await self._vtube_plugin.set_parameter_with_easing(
                "HeadX", 0.3, duration=0.4, easing="easeBoth"
            )
            await asyncio.sleep(0.4)
            await self._vtube_plugin.set_parameter_with_easing(
                "HeadX", -0.3, duration=0.4, easing="easeBoth"
            )
            await asyncio.sleep(0.4)
            await self._vtube_plugin.set_parameter_with_easing(
                "HeadX", 0.0, duration=0.4, easing="easeOut"
            )

    async def _processing_loop(self):
        while True:
            try:
                if self._cognitive_engine:
                    cognitive_state = self._cognitive_engine.get_state()
                    
                    input_data = {
                        "vision": {
                            "target": "",
                            "bandwidth": cognitive_state.get("vision_bandwidth", 0.3),
                            "context": "",
                            "intuitive_tag": "正常"
                        },
                        "audio": {
                            "intent": "",
                            "precision": cognitive_state.get("audio_precision", 0.3),
                            "context": "",
                            "intuitive_tag": "正常"
                        },
                        "thinking": {
                            "cognitive_bandwidth": cognitive_state.get("cognitive_bandwidth", 0.4)
                        }
                    }
                    
                    output = self._cognitive_engine.process(input_data)
                    
                    await self.process_cognitive_output(output)
                
                await asyncio.sleep(1.0)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"认知处理循环异常: {e}")
                await asyncio.sleep(1.0)

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def set_reaction_cooldown(self, cooldown: float):
        self._reaction_cooldown = cooldown

    def get_last_reaction(self) -> CognitiveReactionType:
        return self._last_reaction

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "last_reaction": self._last_reaction.value,
            "reaction_cooldown": self._reaction_cooldown,
            "connected": self._vtube_plugin.is_connected if self._vtube_plugin else False,
            "cognitive_engine_available": self._cognitive_engine is not None
        }


class CognitiveReactionEngine:
    
    def __init__(self):
        self._reaction_rules = [
            {
                "name": "危机检测",
                "condition": lambda output: "危机" in output.vision.intuitive_tag or "危机" in output.audio.intuitive_tag,
                "reaction": CognitiveReactionType.THREATENED,
                "priority": 10
            },
            {
                "name": "美学检测",
                "condition": lambda output: "美学" in output.vision.intuitive_tag or "美学" in output.audio.intuitive_tag,
                "reaction": CognitiveReactionType.BEAUTY_AWE,
                "priority": 9
            },
            {
                "name": "高认知负载",
                "condition": lambda output: output.thinking.cognitive_bandwidth > 0.8,
                "reaction": CognitiveReactionType.FOCUSED,
                "priority": 8
            },
            {
                "name": "空间感知",
                "condition": lambda output: output.thinking.cross_modal_fusion.get("spatial_awareness", False),
                "reaction": CognitiveReactionType.SURPRISED,
                "priority": 7
            },
            {
                "name": "多模态协同",
                "condition": lambda output: "跨模态协同" in output.thinking.cross_modal_fusion.get("emergent_patterns", []),
                "reaction": CognitiveReactionType.EXCITED,
                "priority": 6
            },
            {
                "name": "正常状态",
                "condition": lambda output: output.system_state == "idle",
                "reaction": CognitiveReactionType.NEUTRAL,
                "priority": 1
            }
        ]
        
        self._reaction_rules.sort(key=lambda x: x["priority"], reverse=True)

    def determine_reaction(self, cognitive_output) -> CognitiveReactionType:
        for rule in self._reaction_rules:
            if rule["condition"](cognitive_output):
                return rule["reaction"]
        
        return CognitiveReactionType.NEUTRAL

    def add_rule(self, name: str, condition, reaction: CognitiveReactionType, priority: int = 5):
        self._reaction_rules.append({
            "name": name,
            "condition": condition,
            "reaction": reaction,
            "priority": priority
        })
        self._reaction_rules.sort(key=lambda x: x["priority"], reverse=True)

    def remove_rule(self, name: str):
        self._reaction_rules = [r for r in self._reaction_rules if r["name"] != name]


cognitive_reaction_engine = CognitiveReactionEngine()
cognitive_avatar_controller = CognitiveAvatarController()
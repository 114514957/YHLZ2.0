"""
YHLZ Embodied AI V4.1 - Mock 环境 (Simulation Environment)

职责:
    - 模拟环境状态 / 对象 / 状态变化
    - 支持多场景: 'room' (默认) / 'warehouse' / 自定义
    - Grid World: 对象状态 + 事件变化
    - 用于: 测试 / 演示 / 权限流程验证 / 具身闭环验证 / 预测对照
    - 禁止控制真实设备 (不产生任何真实事件)

设计原则:
    - 线程安全 (RLock)
    - 确定性: 相同动作 → 相同结果, 便于断言
    - 支持: 移动 / 拾取 / 放置 / 扫描 / 检查 / 探索 / 等待
    - 动作结果登记 (action_id → Feedback), 供 feedback() 查询
    - 事件历史记录在状态快照 history 中
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.embodied.environment.interface import Environment
from backend.embodied.schema import (
    EmbodiedAction,
    EmbodiedActionType,
    EmbodiedStatus,
    EnvironmentObject,
    EnvironmentState,
    Feedback,
    FeedbackResult,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# 场景预设
# ----------------------------------------------------------------------

def _room_scene() -> Dict[str, Any]:
    """房间场景 (默认): 台灯 / 箱子 / 书 + 门"""
    return {
        "grid_size": (5, 5),
        "objects": [
            EnvironmentObject.create(
                name="lamp", category="light", position={"x": 1.0, "y": 1.0},
                properties={"color": "white"}, state="on",
            ),
            EnvironmentObject.create(
                name="box", category="container", position={"x": 2.0, "y": 3.0},
                properties={"material": "wood"}, state="closed",
            ),
            EnvironmentObject.create(
                name="book", category="item", position={"x": 0.0, "y": 2.0},
                properties={"title": "YHLZ"}, state="on_table",
            ),
            EnvironmentObject.create(
                name="door", category="structure", position={"x": 4.0, "y": 4.0},
                properties={"material": "metal"}, state="open",
            ),
        ],
        "conditions": {"temperature": 24.0, "lighting": "bright"},
        "relations": [
            {"type": "near", "object_a": "lamp", "object_b": "desk"},
        ],
    }


def _warehouse_scene() -> Dict[str, Any]:
    """仓库场景: 托盘 / 箱子 / 货架 + 门"""
    return {
        "grid_size": (8, 8),
        "objects": [
            EnvironmentObject.create(
                name="pallet", category="container", position={"x": 1.0, "y": 1.0},
                properties={"capacity": 10}, state="loaded",
            ),
            EnvironmentObject.create(
                name="crate", category="container", position={"x": 5.0, "y": 2.0},
                properties={"weight_kg": 25}, state="sealed",
            ),
            EnvironmentObject.create(
                name="shelf", category="structure", position={"x": 6.0, "y": 6.0},
                properties={"height_m": 2.4}, state="full",
            ),
            EnvironmentObject.create(
                name="door", category="structure", position={"x": 0.0, "y": 7.0},
                properties={"material": "metal"}, state="closed",
            ),
        ],
        "conditions": {"temperature": 18.0, "humidity": 45.0},
        "relations": [
            {"type": "on_top_of", "object_a": "crate", "object_b": "pallet"},
        ],
    }


# 场景预设表 (配置驱动入口)
SCENES: Dict[str, Dict[str, Any]] = {
    "room": _room_scene,
    "warehouse": _warehouse_scene,
}


class MockEnvironment(Environment):
    """Mock 环境 (虚拟网格世界, 绝对安全)

    用法:
        env = MockEnvironment(scene="room")
        env = MockEnvironment(grid_size=(5, 5), objects=[...], conditions={...})
    """

    def __init__(
        self,
        scene: Optional[str] = None,
        grid_size: Optional[Tuple[int, int]] = None,
        robot_start: Optional[Tuple[int, int]] = None,
        objects: Optional[List[EnvironmentObject]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        relations: Optional[List[Dict[str, Any]]] = None,
    ):
        self._lock = threading.RLock()

        # 场景解析: scene 指定 → 预设; 否则全默认
        preset: Optional[Dict[str, Any]] = None
        if scene is not None:
            if scene not in SCENES:
                raise ValueError(
                    f"未知场景: {scene} (可选: {list(SCENES.keys())})"
                )
            preset = SCENES[scene]()

        self._grid_size = grid_size or (preset or {}).get("grid_size", (5, 5))
        self._init_robot = list(robot_start or (0, 0))
        self._init_objects = (
            list(objects) if objects is not None
            else list((preset or {}).get("objects", [])) or []
        )
        self._init_conditions = conditions or (preset or {}).get(
            "conditions", {"temperature": 24.0, "lighting": "bright"}
        )
        self._init_relations = relations or (preset or {}).get("relations", [])
        self._scene = scene or "custom"

        self._robot_location: List[float] = list(self._init_robot)
        self._objects: Dict[str, EnvironmentObject] = {
            o.object_id: o for o in self._init_objects
        }
        self._conditions: Dict[str, Any] = dict(self._init_conditions)
        self._relations: List[Dict[str, Any]] = list(self._init_relations)
        self._history: List[Dict[str, Any]] = []
        self._action_results: Dict[str, Feedback] = {}
        self._counter = 0

    # ── 接口实现 ──────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "mock"

    @property
    def scene(self) -> str:
        return self._scene

    @property
    def supported_actions(self) -> List[str]:
        return EmbodiedActionType.values()

    def is_available(self) -> bool:
        return True

    def _snapshot(self) -> EnvironmentState:
        """构建当前状态快照 (内部调用, 需持锁)"""
        return EnvironmentState.create(
            objects=[o for o in self._objects.values()],
            location=dict(zip(("x", "y"), self._robot_location)),
            conditions=dict(self._conditions),
            relations=list(self._relations),
            history=list(self._history[-10:]),
            metadata={
                "environment": self.name,
                "scene": self._scene,
                "grid_size": list(self._grid_size),
                "steps": self._counter,
            },
        )

    def observe(self) -> EnvironmentState:
        with self._lock:
            return self._snapshot()

    def get_state(self) -> EnvironmentState:
        return self.observe()

    def reset(self) -> EnvironmentState:
        """重置为初始状态"""
        with self._lock:
            self._robot_location = list(self._init_robot)
            self._objects = {o.object_id: o for o in self._init_objects}
            self._conditions = dict(self._init_conditions)
            self._relations = list(self._init_relations)
            self._history.append({
                "event": "reset", "timestamp": time.time(),
            })
            self._counter = 0
            state = self._snapshot()
        logger.info(f"[Embodied] Mock 环境已重置 (scene={self._scene})")
        return state

    # ── 动作执行 ──────────────────────────────────────────────────
    def step(self, action: EmbodiedAction) -> EnvironmentState:
        """执行动作, 返回动作后的新状态

        动作类型:
            move:     parameters={'dx': int, 'dy': int} → 移动主体 (越界 → no_change)
            pick:     parameters={'object': name} → 拾取 (同位置 + 对象存在 → success)
            place:    parameters={'object': name} → 放置到当前位置
            scan:     扫描环境 (无状态变化, 返回成功)
            inspect:  parameters={'object': name} → 检查对象
            explore:  探索 (无状态变化, 返回成功)
            wait:     等待 (无状态变化, 返回成功)
        """
        start = time.perf_counter()
        with self._lock:
            if action.action_type not in self.supported_actions:
                return self._finish(
                    action, FeedbackResult.FAILURE.value,
                    error=f"不支持的动作类型: {action.action_type}",
                    latency_ms=(time.perf_counter() - start) * 1000,
                )

            self._counter += 1
            change: Dict[str, Any] = {}
            result = FeedbackResult.SUCCESS.value
            error: Optional[str] = None

            if action.action_type == EmbodiedActionType.MOVE.value:
                result, change, error = self._apply_move(action)
            elif action.action_type == EmbodiedActionType.PICK.value:
                result, change, error = self._apply_pick(action)
            elif action.action_type == EmbodiedActionType.PLACE.value:
                result, change, error = self._apply_place(action)
            elif action.action_type == EmbodiedActionType.INSPECT.value:
                result, change, error = self._apply_inspect(action)
            elif action.action_type in (
                EmbodiedActionType.SCAN.value,
                EmbodiedActionType.EXPLORE.value,
                EmbodiedActionType.WAIT.value,
            ):
                change = {"event": action.action_type}
            else:
                change = {"event": action.action_type, "simulated": True}

            self._history.append({
                "event": action.action_type,
                "target": action.target,
                "result": result,
                "timestamp": time.time(),
            })
            latency = (time.perf_counter() - start) * 1000
            return self._finish(
                action, result, change=change, error=error, latency_ms=latency,
            )

    def _apply_move(self, action: EmbodiedAction) -> Tuple[str, Dict[str, Any], Optional[str]]:
        """移动主体 (网格内移动, 越界失败)"""
        dx = int(action.parameters.get("dx", 0))
        dy = int(action.parameters.get("dy", 0))
        if dx == 0 and dy == 0:
            return FeedbackResult.NO_CHANGE.value, {"event": "move_stationary"}, None
        new_x = self._robot_location[0] + dx
        new_y = self._robot_location[1] + dy
        if not (0 <= new_x < self._grid_size[0] and 0 <= new_y < self._grid_size[1]):
            return (
                FeedbackResult.NO_CHANGE.value,
                {"event": "move_out_of_bounds", "dx": dx, "dy": dy},
                f"移动越界: ({new_x}, {new_y}) 超出网格 {self._grid_size}",
            )
        old = tuple(self._robot_location)
        self._robot_location = [float(new_x), float(new_y)]
        return (
            FeedbackResult.SUCCESS.value,
            {"event": "move", "from": list(old), "to": [new_x, new_y]},
            None,
        )

    def _find_object_by_name(self, name: str) -> Optional[EnvironmentObject]:
        for obj in self._objects.values():
            if obj.name == name:
                return obj
        return None

    def _apply_pick(self, action: EmbodiedAction) -> Tuple[str, Dict[str, Any], Optional[str]]:
        """拾取对象 (需同位置 + 未持有)"""
        name = str(action.parameters.get("object") or action.target)
        obj = self._find_object_by_name(name) if name else None
        if obj is None:
            return (
                FeedbackResult.FAILURE.value, {"event": "pick_missing"},
                f"对象不存在: {name or '(未指定)'}",
            )
        if abs(obj.position.get("x", 0) - self._robot_location[0]) > 1e-6 or \
           abs(obj.position.get("y", 0) - self._robot_location[1]) > 1e-6:
            return (
                FeedbackResult.FAILURE.value,
                {"event": "pick_not_in_reach", "object": name},
                f"对象 {name} 不在当前位置, 无法拾取",
            )
        obj.position = dict(zip(("x", "y"), self._robot_location))
        obj.state = "held"
        return (
            FeedbackResult.SUCCESS.value,
            {"event": "pick", "object": name, "position": self._robot_location},
            None,
        )

    def _apply_place(self, action: EmbodiedAction) -> Tuple[str, Dict[str, Any], Optional[str]]:
        """放置对象 (需持有)"""
        name = str(action.parameters.get("object") or action.target)
        obj = self._find_object_by_name(name) if name else None
        if obj is None:
            return (
                FeedbackResult.FAILURE.value, {"event": "place_missing"},
                f"对象不存在: {name or '(未指定)'}",
            )
        if obj.state != "held":
            return (
                FeedbackResult.FAILURE.value,
                {"event": "place_not_held", "object": name},
                f"对象 {name} 未被持有, 无法放置",
            )
        obj.position = dict(zip(("x", "y"), self._robot_location))
        obj.state = "on_ground"
        return (
            FeedbackResult.SUCCESS.value,
            {"event": "place", "object": name, "position": self._robot_location},
            None,
        )

    def _apply_inspect(self, action: EmbodiedAction) -> Tuple[str, Dict[str, Any], Optional[str]]:
        """检查对象 (读取属性, 无状态变化)"""
        name = str(action.parameters.get("object") or action.target)
        obj = self._find_object_by_name(name) if name else None
        if obj is None:
            return (
                FeedbackResult.FAILURE.value, {"event": "inspect_missing"},
                f"对象不存在: {name or '(未指定)'}",
            )
        return (
            FeedbackResult.SUCCESS.value,
            {
                "event": "inspect", "object": name,
                "category": obj.category, "state": obj.state,
                "properties": obj.properties,
            },
            None,
        )

    def _finish(
        self,
        action: EmbodiedAction,
        result: str,
        change: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        latency_ms: float = 0.0,
    ) -> EnvironmentState:
        """收尾: 登记反馈 + 返回新状态 (需持锁)"""
        action.status = (
            EmbodiedStatus.OK.value if result in (
                FeedbackResult.SUCCESS.value, FeedbackResult.NO_CHANGE.value,
                FeedbackResult.PARTIAL.value,
            ) else EmbodiedStatus.ERROR.value
        )
        state = self._snapshot()
        feedback = Feedback.create(
            action_id=action.action_id, result=result,
            environment_change=change or {}, new_state=state,
            error=error, latency_ms=latency_ms,
        )
        self._action_results[action.action_id] = feedback
        logger.info(
            f"[Embodied] Mock 执行 action_type={action.action_type} "
            f"target={action.target} result={result} latency={latency_ms:.1f}ms"
        )
        return state

    def feedback(self, action_id: str) -> Optional[Feedback]:
        with self._lock:
            return self._action_results.get(action_id)

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "available": self.is_available(),
                "scene": self._scene,
                "grid_size": list(self._grid_size),
                "robot_location": list(self._robot_location),
                "objects": len(self._objects),
                "history_events": len(self._history),
                "total_steps": self._counter,
                "action_results": len(self._action_results),
            }

    def close(self) -> None:
        with self._lock:
            self._action_results.clear()
            self._history.clear()


__all__ = ["MockEnvironment", "SCENES"]

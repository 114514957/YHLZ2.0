"""
YHLZ Embodied AI V4.2 - 状态预测器 (State Predictor)

职责:
    - 根据当前状态 + 动作, 预测环境下一步变化 (规则驱动)
    - 输出 EnvironmentPrediction (expected_change + confidence)
    - 多步骤条件预测 (V4.2): 动作序列 [MOVE, PICK] → 最终预期 (object = held)
    - 状态不变式检测 (V4.2): door=open 不会自动变成 door=closed
    - 为 Agent 决策提供预期 (如 door=open → door remains open)

设计原则:
    - 纯规则预测, 禁止复杂 AI 训练 (禁止黑盒预测)
    - 确定性: 相同输入 → 相同输出, 便于断言
    - 线程安全 (RLock)
    - 预测不等于执行: 预测结果必须经 Permission → Executor 才能落地
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.embodied.reasoning.invariants import InvariantChecker
from backend.embodied.schema import (
    EmbodiedAction,
    EmbodiedActionType,
    EnvironmentObject,
    EnvironmentPrediction,
    EnvironmentState,
    MultiStepPrediction,
)

logger = logging.getLogger(__name__)


class PredictorError(Exception):
    """预测器操作异常"""


class StatePredictor:
    """状态预测器 (规则驱动)

    用法:
        predictor = StatePredictor()
        prediction = predictor.predict(action, current_state)
    """

    def __init__(self, default_confidence: float = 0.8):
        self._lock = threading.RLock()
        self._default_confidence = default_confidence
        self._invariants = InvariantChecker()

    # ── 多步骤条件预测 (V4.2) ────────────────────────────────────
    def predict_sequence(
        self,
        actions: List[EmbodiedAction],
        current_state: Optional[EnvironmentState] = None,
    ) -> MultiStepPrediction:
        """多步骤条件预测: 动作序列 → 逐步预期 + 最终预期

        例: [MOVE(dx=1), PICK(lamp)] → steps=[位置变化, 拾取成功] → final {lamp: held}

        设计:
            - 规则驱动状态推演 (move/pick/place 逐步模拟)
            - 每步输出 expected / confidence
            - 检测状态不变式 (invariants_ok / invariant_violations)
        """
        if actions is None or not actions:
            return MultiStepPrediction.create(
                actions=[],
                steps=[],
                final_expected={},
                invariants_ok=True,
                confidence=self._default_confidence,
            )

        state = self._simulate_copy(current_state)
        steps: List[Dict[str, Any]] = []
        violations: List[Dict[str, Any]] = []
        prev_state = self._simulate_copy(current_state)

        with self._lock:
            for i, action in enumerate(actions):
                pred = self.predict(action, state)
                step: Dict[str, Any] = {
                    "index": i,
                    "action": action.action_type,
                    "target": action.target,
                    "expected": pred.expected_change,
                    "confidence": pred.confidence,
                }
                steps.append(step)
                # 规则推演: 应用预期变化到模拟状态
                state = self._apply_prediction(action, state, pred)
                # 不变式检测 (单步): 动作目标对象的状态变化视为动作解释
                target_name = str(
                    action.parameters.get("object") or action.target or ""
                )
                allowed = [target_name] if target_name else []
                step_violations = self._invariants.check(
                    prev_state, state,
                    action_types=[action.action_type],
                    allowed_state_changes=allowed,
                )
                violations.extend(step_violations)
                if step_violations:
                    step["invariant_violations"] = step_violations
                prev_state = self._simulate_copy(state)

            final_expected = self._describe_state(state)
            # 整体不变式 (位置变化豁免: 序列内含 move; 状态变化由动作解释)
            seq_violations = self._invariants.check(
                self._simulate_copy(current_state), state,
                action_types=[a.action_type for a in actions],
                allowed_state_changes=[
                    str(a.parameters.get("object") or a.target or "")
                    for a in actions if a.target or a.parameters.get("object")
                ],
            )
            if seq_violations:
                violations.extend(seq_violations)

            avg_conf = (
                sum(s.get("confidence", 0.0) for s in steps) / len(steps)
                if steps else self._default_confidence
            )
            return MultiStepPrediction.create(
                actions=[a.to_dict() for a in actions],
                steps=steps,
                final_expected=final_expected,
                invariants_ok=not violations,
                invariant_violations=violations,
                confidence=round(avg_conf, 4),
            )

    def check_invariants(
        self,
        actions: List[EmbodiedAction],
        current_state: Optional[EnvironmentState] = None,
    ) -> List[Dict[str, Any]]:
        """检测动作序列预测是否违反状态不变式 (仅检测, 不修改)"""
        state = self._simulate_copy(current_state)
        action_types = [a.action_type for a in actions]
        allowed_state_changes = [
            str(a.parameters.get("object") or a.target or "")
            for a in actions if a.target or a.parameters.get("object")
        ]
        with self._lock:
            for action in actions:
                pred = self.predict(action, state)
                state = self._apply_prediction(action, state, pred)
            return self._invariants.check(
                self._simulate_copy(current_state), state,
                action_types=action_types,
                allowed_state_changes=allowed_state_changes,
            )

    @staticmethod
    def _simulate_copy(state: Optional[EnvironmentState]) -> EnvironmentState:
        """深拷贝状态 (推演用, 不污染世界模型)"""
        if state is None:
            return EnvironmentState.create()
        return EnvironmentState.from_dict(state.to_dict())

    @staticmethod
    def _apply_prediction(
        action: EmbodiedAction,
        state: EnvironmentState,
        pred: EnvironmentPrediction,
    ) -> EnvironmentState:
        """按预测应用变化到模拟状态 (纯规则, 与 Mock 环境行为一致)"""
        change = pred.expected_change or {}
        expected = change.get("expected")
        state = StatePredictor._simulate_copy(state)
        if expected == "position_change":
            to_pos = change.get("to")
            if isinstance(to_pos, list) and len(to_pos) == 2:
                state.location = {"x": float(to_pos[0]), "y": float(to_pos[1])}
        if expected == "success":
            obj_name = change.get("object")
            if obj_name:
                for o in state.objects:
                    if o.name == obj_name:
                        o.state = change.get("state", o.state)
                        # 拾取/放置同步对象位置到主体位置 (与 Mock 一致)
                        if action.action_type in (
                            EmbodiedActionType.PICK.value,
                            EmbodiedActionType.PLACE.value,
                        ):
                            o.position = dict(state.location)
        return state

    @staticmethod
    def _describe_state(state: EnvironmentState) -> Dict[str, Any]:
        """最终状态摘要: 对象状态 + 主体位置"""
        objects = {
            o.name: o.state for o in state.objects if o.state
        }
        return {
            "objects": objects,
            "location": state.location,
        }

    # ── 主入口 ────────────────────────────────────────────────────
    def predict(
        self,
        action: Optional[EmbodiedAction],
        current_state: Optional[EnvironmentState] = None,
    ) -> EnvironmentPrediction:
        """预测动作后的环境变化

        Args:
            action: 待执行动作 (None=仅稳定性预测)
            current_state: 当前状态 (None=无状态预测)

        Returns:
            EnvironmentPrediction (expected_change + confidence)
        """
        if action is None:
            return self._predict_stability(current_state)

        action_type = action.action_type
        state = current_state or EnvironmentState.create()
        with self._lock:
            if action_type == EmbodiedActionType.MOVE.value:
                return self._predict_move(action, state)
            if action_type == EmbodiedActionType.PICK.value:
                return self._predict_pick(action, state)
            if action_type == EmbodiedActionType.PLACE.value:
                return self._predict_place(action, state)
            if action_type == EmbodiedActionType.INSPECT.value:
                return self._predict_inspect(action, state)
            # SCAN / EXPLORE / WAIT / INTERACT / CUSTOM → 无状态变化预期
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={
                    "event": action_type,
                    "expected": "no_change",
                    "note": "该动作不改变对象状态或主体位置",
                },
                confidence=self._default_confidence,
            )

    # ── 各动作预测规则 ────────────────────────────────────────────
    def _predict_move(
        self, action: EmbodiedAction, state: EnvironmentState
    ) -> EnvironmentPrediction:
        """预测移动: 位置变化 (受环境边界限制)"""
        try:
            dx = int(action.parameters.get("dx", 0))
            dy = int(action.parameters.get("dy", 0))
        except (TypeError, ValueError):
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={"event": "move", "expected": "unknown", "error": "dx/dy 不合法"},
                confidence=0.3,
            )

        new_x = state.location.get("x", 0.0) + dx
        new_y = state.location.get("y", 0.0) + dy
        grid = state.metadata.get("grid_size")
        in_bounds = True
        if isinstance(grid, list) and len(grid) == 2:
            in_bounds = 0 <= new_x < grid[0] and 0 <= new_y < grid[1]

        if dx == 0 and dy == 0:
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={"event": "move", "expected": "no_change", "reason": "原地移动"},
                confidence=0.9,
            )
        if not in_bounds:
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={
                    "event": "move", "expected": "no_change",
                    "reason": f"目标位置 ({new_x}, {new_y}) 超出环境边界",
                },
                confidence=0.9,
            )
        return EnvironmentPrediction.create(
            current_state=state,
            expected_change={
                "event": "move", "expected": "position_change",
                "to": [new_x, new_y],
            },
            confidence=0.9,
        )

    def _find_object(self, state: EnvironmentState, action: EmbodiedAction) -> Optional[EnvironmentObject]:
        name = str(action.parameters.get("object") or action.target)
        if not name:
            return None
        for o in state.objects:
            if o.name == name:
                return o
        return None

    def _predict_pick(
        self, action: EmbodiedAction, state: EnvironmentState
    ) -> EnvironmentPrediction:
        """预测拾取: 对象被持有 (需同位置)"""
        obj = self._find_object(state, action)
        if obj is None:
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={"event": "pick", "expected": "failure", "reason": "对象不存在"},
                confidence=0.9,
            )
        same_pos = (
            abs(obj.position.get("x", 0) - state.location.get("x", 0)) <= 1e-6
            and abs(obj.position.get("y", 0) - state.location.get("y", 0)) <= 1e-6
        )
        if not same_pos:
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={
                    "event": "pick", "expected": "failure",
                    "reason": "对象不在当前位置, 无法拾取",
                    "suggestion": "先移动到对象附近再拾取",
                },
                confidence=0.9,
            )
        return EnvironmentPrediction.create(
            current_state=state,
            expected_change={
                "event": "pick", "expected": "success",
                "object": obj.name, "state": "held",
            },
            confidence=0.9,
        )

    def _predict_place(
        self, action: EmbodiedAction, state: EnvironmentState
    ) -> EnvironmentPrediction:
        """预测放置: 对象落地 (需持有)"""
        obj = self._find_object(state, action)
        if obj is None:
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={"event": "place", "expected": "failure", "reason": "对象不存在"},
                confidence=0.9,
            )
        if obj.state != "held":
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={
                    "event": "place", "expected": "failure",
                    "reason": "对象未被持有", "suggestion": "先拾取对象再放置",
                },
                confidence=0.9,
            )
        return EnvironmentPrediction.create(
            current_state=state,
            expected_change={
                "event": "place", "expected": "success",
                "object": obj.name, "state": "on_ground",
            },
            confidence=0.9,
        )

    def _predict_inspect(
        self, action: EmbodiedAction, state: EnvironmentState
    ) -> EnvironmentPrediction:
        """预测检查: 无状态变化"""
        obj = self._find_object(state, action)
        if obj is None:
            return EnvironmentPrediction.create(
                current_state=state,
                expected_change={"event": "inspect", "expected": "failure", "reason": "对象不存在"},
                confidence=0.9,
            )
        return EnvironmentPrediction.create(
            current_state=state,
            expected_change={"event": "inspect", "expected": "no_change", "object": obj.name},
            confidence=0.95,
        )

    def _predict_stability(self, current_state: Optional[EnvironmentState]) -> EnvironmentPrediction:
        """稳定性预测: 无动作时状态保持 (如 door=open → remains open)"""
        state = current_state or EnvironmentState.create()
        objects_snapshot = [
            {"name": o.name, "state": o.state} for o in state.objects
        ]
        return EnvironmentPrediction.create(
            current_state=state,
            expected_change={
                "event": "stability",
                "expected": "no_change",
                "note": "无外部动作, 环境状态保持不变",
                "objects": objects_snapshot,
            },
            confidence=0.95,
        )

    # ── 预测验证 (执行后对照) ─────────────────────────────────────
    def verify(
        self,
        prediction: EnvironmentPrediction,
        actual_change: Dict[str, Any],
    ) -> Dict[str, Any]:
        """对照预测与实际变化, 输出验证结果 (供学习反馈)"""
        expected = (prediction.expected_change or {}).get("expected", "unknown")
        actual_event = (actual_change or {}).get("event", "unknown")
        matched = expected == actual_event
        return {
            "matched": matched,
            "expected": expected,
            "actual": actual_event,
            "confidence": prediction.confidence,
            "note": "预测准确" if matched else "预测与实际不符, 已记录",
        }

    def status(self) -> Dict[str, Any]:
        return {
            "mode": "rule_based",
            "default_confidence": self._default_confidence,
            "supported_actions": EmbodiedActionType.values(),
            "multi_step_prediction": True,
            "invariant_checking": True,
            "note": "纯规则预测 + 多步条件推演, 无 AI 训练",
        }

    def reset(self) -> None:
        with self._lock:
            self._invariants.reset()


__all__ = ["StatePredictor", "PredictorError"]

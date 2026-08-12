"""
YHLZ Voice Identity System V2.1 - 结果对象 (Rust 风格 Ok/Err)

职责:
    - 提供 Result[T] 泛型封装, 替代裸异常用于 Pipeline 阶段返回
    - Ok(value) 表示成功并携带值
    - Err(error) 表示失败并携带错误信息 (字符串或异常)

设计原则:
    - 不可变 (frozen dataclass)
    - 链式: .map / .and_then / .unwrap_or
    - 与现有异常体系共存: Pipeline 内部用 Result, 对外可 unwrap_or_raise 抛异常
    - 不引入新依赖, 仅用 stdlib + typing.Generic
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, TypeVar

T = TypeVar("T")
U = TypeVar("U")


class ResultError(Exception):
    """Result 操作本身的异常 (如对 Err 调 unwrap)"""


@dataclass(frozen=True)
class Result(Generic[T]):
    """Result 基类: Ok / Err 的共同接口

    使用:
        r = Ok(42)
        r.unwrap()        # 42
        r.map(lambda x: x+1).unwrap()  # 43

        e = Err("失败")
        e.unwrap_or(0)    # 0
        e.unwrap_or_raise(MyError)  # raise MyError("失败")
    """
    is_ok: bool
    value: Optional[T] = None
    error: Optional[Any] = None

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def is_err(self) -> bool:
        return not self.is_ok

    def ok(self) -> Optional[T]:
        """成功值或 None"""
        return self.value if self.is_ok else None

    def err(self) -> Optional[Any]:
        """失败值或 None"""
        return self.error if self.is_err else None

    # ------------------------------------------------------------------
    # 链式
    # ------------------------------------------------------------------

    def map(self, fn: Callable[[T], U]) -> "Result[U]":
        """成功时对值应用 fn; 失败透传"""
        if self.is_ok:
            try:
                return Ok(fn(self.value))  # type: ignore[arg-type]
            except Exception as e:
                return Err(e)
        return Err(self.error)  # type: ignore[arg-type]

    def and_then(self, fn: Callable[[T], "Result[U]"]) -> "Result[U]":
        """单子绑定: 成功时 fn 返回 Result; 失败透传"""
        if self.is_ok:
            try:
                return fn(self.value)  # type: ignore[arg-type]
            except Exception as e:
                return Err(e)
        return Err(self.error)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # 解包
    # ------------------------------------------------------------------

    def unwrap(self) -> T:
        """成功返值; 失败抛 ResultError"""
        if self.is_ok:
            return self.value  # type: ignore[return-value]
        raise ResultError(f"unwrap 失败: {self.error}")

    def unwrap_or(self, default: T) -> T:
        """成功返值; 失败返 default"""
        return self.value if self.is_ok else default  # type: ignore[return-value]

    def unwrap_or_raise(self, exc_cls: type) -> T:
        """成功返值; 失败抛 exc_cls(error)"""
        if self.is_ok:
            return self.value  # type: ignore[return-value]
        raise exc_cls(self.error) if self.error is not None else exc_cls()


def Ok(value: T) -> "Result[T]":
    """构造成功结果"""
    return Result(is_ok=True, value=value, error=None)


def Err(error: Any) -> "Result[Any]":
    """构造失败结果 (error 可为 str/Exception/任意对象)"""
    if isinstance(error, BaseException):
        return Result(is_ok=False, value=None, error=str(error) or error.__class__.__name__)
    return Result(is_ok=False, value=None, error=error)

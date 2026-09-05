"""Read-only boundary for protected memory during runtime-chain refactoring."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from backend.session_kernel import ErrorCode


class MemoryWriteBlocked(PermissionError):
    code = ErrorCode.MEMORY_WRITE_BLOCKED.value


class ReadOnlyMemoryFacade:
    """Expose reads while making all persistence mutations fail closed.

    Reconnect, restart, and reset apply only to this facade's runtime counters;
    none of them invoke a storage mutation callback.
    """

    def __init__(
        self,
        reader: Optional[Callable[[str], Any]] = None,
        searcher: Optional[Callable[[str, int], Iterable[Any]]] = None,
        name: str = "protected_memory",
    ) -> None:
        self._reader = reader
        self._searcher = searcher
        self.name = name
        self._reconnects = 0
        self._restarts = 0
        self._runtime_resets = 0

    def get(self, key: str) -> Any:
        return self._reader(key) if self._reader else None

    def search(self, query: str, limit: int = 5) -> list:
        if limit < 0:
            raise ValueError("limit must not be negative")
        if not self._searcher:
            return []
        return list(self._searcher(query, limit))

    def reconnect(self) -> None:
        self._reconnects += 1

    def restart_runtime(self) -> None:
        self._restarts += 1

    def reset_runtime(self) -> None:
        self._runtime_resets += 1

    def runtime_status(self) -> dict:
        return {
            "name": self.name,
            "mode": "read_only",
            "reconnects": self._reconnects,
            "restarts": self._restarts,
            "runtime_resets": self._runtime_resets,
        }

    def add(self, *args: Any, **kwargs: Any) -> None:
        self._deny("add")

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._deny("update")

    def delete(self, *args: Any, **kwargs: Any) -> None:
        self._deny("delete")

    def clear(self, *args: Any, **kwargs: Any) -> None:
        self._deny("clear")

    def commit(self, *args: Any, **kwargs: Any) -> None:
        self._deny("commit")

    def _deny(self, action: str) -> None:
        raise MemoryWriteBlocked(
            "{0}: {1} is blocked while the target chain is read-only".format(
                MemoryWriteBlocked.code, action
            )
        )


__all__ = ["MemoryWriteBlocked", "ReadOnlyMemoryFacade"]

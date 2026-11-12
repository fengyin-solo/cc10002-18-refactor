"""契约注册表测试：装载边界、失败保留旧契约、并发只发布一份完整版本。"""
from __future__ import annotations

import threading
import time

import pytest

from app.contracts import ContractConflictError, ContractRegistry, FieldDeclaration
from app.contracts.compiler import compile_contracts
from app.contracts.declarations import (
    DATAMODEL_DECLARATION,
    DIMENSION_DECLARATION,
)

GOOD = (DIMENSION_DECLARATION, DATAMODEL_DECLARATION)


def f(key: str, *, index: int | None = None) -> FieldDeclaration:
    return FieldDeclaration(key, key, field_index=index)


def broken_declarations():
    """一组必然编译失败的声明：同模块两个描述指向同一旧键。"""
    from app.contracts import ModuleDeclaration
    return (
        ModuleDeclaration(name="dimension", display_name="分析维度", fields=(
            f("维度编号", index=0), f("维度编号", index=1),
        )),
    )


class TestLoadBoundary:
    def test_first_load_publishes_complete_snapshot(self):
        registry = ContractRegistry(GOOD)
        assert registry.is_loaded() is False
        with pytest.raises(ContractConflictError, match="尚未成功装载"):
            _ = registry.snapshot
        snapshot = registry.load()
        assert registry.is_loaded() is True
        assert registry.snapshot is snapshot
        assert snapshot.names() == ("dimension", "datamodel")

    def test_repeated_load_returns_same_snapshot(self):
        registry = ContractRegistry(GOOD)
        first = registry.load()
        assert registry.load() is first
        assert registry.snapshot is first

    def test_initial_failure_publishes_nothing(self):
        registry = ContractRegistry(broken_declarations())
        with pytest.raises(ContractConflictError):
            registry.load()
        assert registry.is_loaded() is False
        with pytest.raises(ContractConflictError, match="尚未成功装载"):
            _ = registry.snapshot

    def test_reload_failure_keeps_previous_complete_contract(self):
        registry = ContractRegistry(GOOD)
        old = registry.load()
        holder = registry.snapshot  # 读者已持有的稳定快照

        with pytest.raises(ContractConflictError):
            registry.reload_from(broken_declarations())

        # 发布面保持旧的完整契约，读者持有的引用不受任何影响。
        assert registry.is_loaded() is True
        assert registry.snapshot is old
        assert holder is old
        assert registry.snapshot.names() == ("dimension", "datamodel")

    def test_reload_success_publishes_new_full_version(self):
        from app.contracts import ModuleDeclaration
        registry = ContractRegistry(GOOD)
        old = registry.load()

        extended = (
            DIMENSION_DECLARATION,
            DATAMODEL_DECLARATION,
            ModuleDeclaration(name="extra", display_name="扩展实体", fields=(
                f("扩展编号", index=0), f("扩展名称", index=1),
            )),
        )
        new = registry.reload_from(extended)
        assert new is not old
        assert registry.snapshot is new
        assert new.names() == ("dimension", "datamodel", "extra")
        # 旧快照仍自洽，已持有它的读者不会看到中途状态。
        assert old.names() == ("dimension", "datamodel")

    def test_declaration_source_copied_defensively(self):
        source = list(GOOD)
        registry = ContractRegistry(source)
        registry.load()
        source.clear()  # 外部改动声明容器
        assert registry.snapshot.names() == ("dimension", "datamodel")


class TestConcurrentPublication:
    def test_concurrent_initial_load_compiles_once(self):
        calls = {"count": 0}

        def compiler(declarations):
            # 注册表锁保证编译器串行进入；模拟真实编译耗时以放大竞争窗口。
            calls["count"] += 1
            time.sleep(0.02)
            return compile_contracts(declarations)

        registry = ContractRegistry(GOOD, compiler=compiler)
        results: list = []
        errors: list = []

        def worker():
            try:
                results.append(registry.load())
            except Exception as exc:  # pragma: no cover - 仅用于暴露并发缺陷
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert calls["count"] == 1
        assert len(results) == 8
        assert all(item is results[0] for item in results)

    def test_concurrent_reload_never_publishes_partial_contract(self):
        registry = ContractRegistry(GOOD)
        registry.load()
        observed: list[tuple[str, ...]] = []
        observations_lock = threading.Lock()

        def worker(rounds: int, use_broken: bool):
            for _ in range(rounds):
                try:
                    if use_broken:
                        registry.reload_from(broken_declarations())
                    else:
                        registry.reload_from(GOOD)
                except ContractConflictError:
                    pass
                # 无论编译成功与否，任何时刻能读到的发布版本都必须完整。
                with observations_lock:
                    observed.append(registry.snapshot.names())

        threads = [
            threading.Thread(target=worker, args=(20, i % 2 == 0))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        valid = {("dimension", "datamodel")}
        assert observed, "并发过程中应至少观测到一次发布版本"
        assert set(observed) <= valid
        # 失败声明从未被发布，最终版本仍是完整契约。
        assert registry.snapshot.names() == ("dimension", "datamodel")

    def test_holders_keep_stable_snapshot_under_reload(self):
        registry = ContractRegistry(GOOD)
        held = registry.load()
        holder_seen: list = []

        def reader(stop: threading.Event):
            while not stop.is_set():
                holder_seen.append(held.names())

        stop = threading.Event()
        reader_thread = threading.Thread(target=reader, args=(stop,))
        reader_thread.start()
        for _ in range(10):
            try:
                registry.reload_from(broken_declarations())
            except ContractConflictError:
                pass
            registry.reload()
        stop.set()
        reader_thread.join()
        assert holder_seen and all(names == ("dimension", "datamodel")
                                   for names in holder_seen)


class TestGlobalRegistry:
    def test_process_singleton_is_loaded_and_complete(self):
        from app.contracts import load_contracts, registry
        snapshot = load_contracts()
        assert registry.snapshot is snapshot
        assert load_contracts() is snapshot

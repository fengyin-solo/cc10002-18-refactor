"""字段契约注册表：控制契约的编译、装载与发布边界。

装载策略对应重构要求里的「整体边界」：

* 进程启动时 eagerly 编译一次；首次编译失败直接抛错，服务不带着残缺契约启动。
* 每次重新编译都在锁内完成，**只有整份快照编译成功才原子发布**；编译失败时
  已经持有的旧完整契约原样保留，已拿到旧快照的读者继续使用，不受影响。
* 发布出去的是 :class:`~app.contracts.compiler.ContractsSnapshot` 冻结快照，
  并发编译或初始化只会发布一份完整版本，读者不会读到半新半旧的中间态。
* 注册表只暴露只读访问入口，外部消费者拿到的字典/字段集合均为冻结对象，
  无法通过改动描述反向影响另一个模块。
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from app.contracts.compiler import ContractsSnapshot, ContractConflictError, compile_contracts
from app.contracts.declarations import MODULE_DECLARATIONS, ModuleDeclaration


class ContractRegistry:
    """进程内字段契约注册表；声明来源可注入，便于测试装载失败等场景。"""

    def __init__(
        self,
        declarations: Sequence[ModuleDeclaration] = MODULE_DECLARATIONS,
        compiler: Callable[[tuple[ModuleDeclaration, ...]], ContractsSnapshot] = compile_contracts,
    ) -> None:
        self._lock = threading.RLock()
        self._declarations = tuple(declarations)
        self._compiler = compiler
        self._snapshot: ContractsSnapshot | None = None

    def load(self) -> ContractsSnapshot:
        """首次装载：编译并发布完整快照；失败时进程内不存在任何已发布契约。"""
        with self._lock:
            if self._snapshot is None:
                self._snapshot = self._compiler(self._declarations)
            return self._snapshot

    def reload(self) -> ContractsSnapshot:
        """重新编译并原子发布；编译失败则保留并返回旧的完整契约，同时抛出冲突。

        与首次装载不同，热装载失败属于运行期事件：旧契约仍然可用，异常交由调用方
        记录处理，已经持有旧快照的读者完全无感知。
        """
        with self._lock:
            candidate = self._compiler(self._declarations)
            # 编译成功之后才覆盖引用，发布动作是一次引用替换，对读者原子可见。
            self._snapshot = candidate
            return candidate

    def reload_from(self, declarations: Sequence[ModuleDeclaration]) -> ContractsSnapshot:
        """用一组临时声明重新编译；失败时保留旧契约，成功后替换声明来源并发布。"""
        with self._lock:
            candidate = self._compiler(tuple(declarations))
            self._declarations = tuple(declarations)
            self._snapshot = candidate
            return candidate

    @property
    def snapshot(self) -> ContractsSnapshot:
        """当前已发布的稳定快照；从未成功装载时显式报错，不返回半成品。"""
        current = self._snapshot
        if current is None:
            raise ContractConflictError(["字段契约尚未成功装载，没有可用的完整契约"])
        return current

    def contract(self, module_name: str) -> "object":
        return self.snapshot.get(module_name)

    def is_loaded(self) -> bool:
        return self._snapshot is not None


#: 进程级单例注册表。导入本模块即完成声明接线，但编译在首次 load() 时发生。
registry = ContractRegistry()


def load_contracts() -> ContractsSnapshot:
    """应用启动入口：一次性编译并发布完整字段契约。"""
    return registry.load()


def get_contract(module_name: str):
    """适配层统一入口：按模块名取只读字段契约。"""
    return registry.snapshot.get(module_name)

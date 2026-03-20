from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeAlias, NamedTuple
from types import ModuleType


class HookType(Enum):
    """The phase during which an API hook should execute."""

    BEFORE = "before"
    AFTER = "after"
    OVERRIDE = "override"


AddonPath: TypeAlias = str
AddonName: TypeAlias = str
SystemKey: TypeAlias = Optional[tuple[str, ...]]


class ExecutionStep(NamedTuple):
    func: Callable
    ctx_mode: bool
    name: str
    addon_name: str
    system_name: SystemKey
    is_main: bool
    step_hash: str
    is_async: bool
    is_generator: bool
    generator_mode: str = "append"
    is_async_gen: bool = False


@dataclass
class ExecutionChainStep:
    main: ExecutionStep
    before: list["ExecutionChainStep"] = field(default_factory=list)
    old_main: list["ExecutionChainStep"] = field(default_factory=list)
    after: list["ExecutionChainStep"] = field(default_factory=list)


@dataclass
class APIVersion:
    """Represents a semantic version for an API."""

    major: int | None = None
    minor: int | None = None
    patch: int | None = None

    @property
    def is_none(self):
        return self.major is None and self.minor is None and self.patch is None

    def __str__(self):
        if self.is_none:
            return "None"
        return f"{self.major or 0}.{self.minor or 0}.{self.patch or 0}"

    def __repr__(self):
        return f"APIVersion({self.__str__()})"

    def to_tuple(self):
        return (self.major, self.minor, self.patch)

    @classmethod
    def from_tuple(cls, t: tuple[int, int, int]):
        return cls(t[0], t[1], t[2])

    def match(self, constraint: str) -> bool:
        """Evaluates whether this version satisfies the given constraint."""
        if not constraint:
            return True
        try:
            if self.is_none:
                return False

            op, ver_str = "==", constraint
            for check_op in (">=", "<=", "==", ">", "<"):
                if constraint.startswith(check_op):
                    op = check_op
                    ver_str = constraint[len(check_op) :]
                    break

            parts = [int(x) for x in ver_str.split(".")]
            major_req = parts[0]
            minor_req = parts[1] if len(parts) > 1 else 0
            patch_req = parts[2] if len(parts) > 2 else 0

            self_tuple = (self.major or 0, self.minor or 0, self.patch or 0)
            req_tuple = (major_req, minor_req, patch_req)

            if op == ">=":
                return self_tuple >= req_tuple
            if op == "<=":
                return self_tuple <= req_tuple
            if op == ">":
                return self_tuple > req_tuple
            if op == "<":
                return self_tuple < req_tuple

            # Default is "=="
            if self.major != major_req:
                return False
            if len(parts) > 1 and self.minor != minor_req:
                return False
            if len(parts) > 2 and self.patch != patch_req:
                return False
            return True

        except Exception as exc:
            raise ValueError(f"Invalid version constraint: {constraint}") from exc


@dataclass
class APIContext:
    """Context object passed to API hooks."""

    api_name: str
    calling_addon: str
    args: list[Any]
    kwargs: dict[str, Any]
    arguments: dict[str, Any] = field(default_factory=dict)
    _store: dict[str, Any] = field(default_factory=dict)

    active_addon: str = ""
    active_system: SystemKey = None
    active_function: str = ""
    is_main: bool = False
    unstable_hashes: dict[str, str] = field(default_factory=dict)
    active_hash: str | None = ""
    target_hash: str | None = ""

    # Shared results container so result is a reference rather than a value
    _results: dict[str, Any] = field(default_factory=lambda: {"result": None})
    original_generator: Any = None

    @property
    def result(self):
        return self._results["result"]

    @result.setter
    def result(self, value):
        self._results["result"] = value

    def get_data(self, key: str) -> Optional[Any]:
        """Retrieves data stored in the context by hooks."""
        return self._store.get(key)

    def set_data(self, key: str, value):
        """Stores data in the context for other hooks to use."""
        self._store[key] = value

    def copy(self) -> "APIContext":
        """Creates a shallow copy of the context, preserving the shared data store."""
        return APIContext(
            api_name=self.api_name,
            calling_addon=self.calling_addon,
            args=self.args.copy(),
            kwargs=self.kwargs.copy(),
            arguments=self.arguments.copy(),
            _store=self._store,
            active_addon=self.active_addon,
            active_system=self.active_system,
            active_function=self.active_function,
            is_main=self.is_main,
            unstable_hashes=self.unstable_hashes,
            active_hash=self.active_hash,
            target_hash=self.target_hash,
            _results=self._results,
            original_generator=self.original_generator,
        )

    def get_args(self, *names: str) -> tuple:
        """Retrieves bound arguments by name, regardless of whether they were passed as args or kwargs."""
        return tuple(self.arguments.get(name) for name in names)


@dataclass
class RuntimeFunction:
    """Represents a registered API function."""

    system: "RuntimeSystem"
    name: str
    func: Callable
    version: APIVersion
    docs: str = ""
    is_unstable: bool = False
    from_hook: bool = False
    hash: str = ""


@dataclass
class RuntimeTargetFunction:
    addon: AddonName
    function: str
    system: SystemKey = None
    version_constraint: str = ""
    expected_hashes: list[str] = field(default_factory=list)
    error_on_hash_mismatch: bool = False

    def to_dict(self):
        return {
            "addon": self.addon,
            "function": self.function,
            "system": self.system,
            "version_constraint": self.version_constraint,
            "expected_hashes": self.expected_hashes,
            "error_on_hash_mismatch": self.error_on_hash_mismatch,
        }

    @classmethod
    def from_dict(cls, data: dict):
        for key in {"addon", "function", "system", "version_constraint"}:
            assert key in data, f"Missing key in RuntimeTargetFunction: {key}"
        return cls(
            data["addon"],
            data["function"],
            data["system"],
            data["version_constraint"],
            data.get("expected_hashes", []),
            data.get("error_on_hash_mismatch", False),
        )


@dataclass(unsafe_hash=True)
class RuntimeTargetAddon:
    addon: AddonName
    system: SystemKey

    def to_dict(self):
        return {"addon": self.addon, "system": self.system}

    @classmethod
    def from_dict(cls, data: dict):
        for key in {"addon", "system"}:
            assert key in data, f"Missing key in RuntimeTargetAddon: {key}"
        return cls(data["addon"], data["system"])


@dataclass
class RuntimeExposedHook:
    name: str
    version: APIVersion = field(default_factory=APIVersion)
    is_unstable: bool = False
    hash: str = ""

    def to_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "is_unstable": self.is_unstable,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict):
        for key in {"name", "version"}:
            assert key in data, f"Missing key in RuntimeExposedHook: {key}"
        return cls(
            data["name"],
            data["version"],
            data.get("is_unstable", False),
            data.get("hash", ""),
        )


@dataclass
class RuntimeHook:
    """Represents a registered API hook."""

    system: "RuntimeSystem"
    target: RuntimeTargetFunction
    func: Callable
    hook_type: HookType
    version_constraint: str = ">=1.0"
    yields_to: list[RuntimeTargetFunction] = field(default_factory=list)
    requires_provider: list[RuntimeTargetAddon] = field(default_factory=list)
    expose_api_as: Optional[RuntimeExposedHook] = None
    generator_mode: str = "append"


@dataclass
class RuntimeWaiter:
    """Represents a callback waiting for a system lifecycle event."""

    callback_func: Callable


@dataclass
class RuntimeSystem:
    """Represents a system containing functions and hooks."""

    addon: "RuntimeAddon"
    name: SystemKey
    module: ModuleType | None = None
    functions: dict[str, RuntimeFunction] = field(default_factory=dict)
    hooks: list[RuntimeHook] = field(default_factory=list)
    ready: bool = False
    on_ready: dict[RuntimeTargetAddon, list[RuntimeWaiter]] = field(
        default_factory=dict
    )
    on_exit: dict[RuntimeTargetAddon, list[RuntimeWaiter]] = field(default_factory=dict)


@dataclass
class RuntimeAddon:
    """Represents an addon containing systems."""

    name: AddonName
    path: AddonPath
    instance_version: int
    bl_info: dict = field(default_factory=dict)
    systems: dict[SystemKey, RuntimeSystem] = field(default_factory=dict)


@dataclass
class RuntimeExecutionNode:
    func: Callable
    system: "RuntimeSystem"
    name: str | None = None
    version: APIVersion = field(default_factory=APIVersion)
    hash: str = ""
    generator_mode: str = "append"


@dataclass
class RuntimeExecutionChain:
    main: RuntimeExecutionNode
    before: list["RuntimeExecutionChain"] = field(default_factory=list)
    old_main: list["RuntimeExecutionChain"] = field(default_factory=list)
    after: list["RuntimeExecutionChain"] = field(default_factory=list)

    def change_main(self, new: RuntimeExecutionNode):
        old_chain = RuntimeExecutionChain(
            main=self.main, before=self.before, old_main=[], after=self.after
        )
        self.old_main.append(old_chain)
        self.main = new
        self.before = []
        self.after = []

    def add_hook(self, hook_type: HookType, chain: "RuntimeExecutionChain"):
        if hook_type == HookType.BEFORE:
            self.before.append(chain)
        elif hook_type == HookType.AFTER:
            self.after.append(chain)


MY_VERSION = 1

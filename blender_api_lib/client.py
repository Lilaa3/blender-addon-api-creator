import dataclasses
import logging
import inspect
import fnmatch
import functools
from types import ModuleType
from typing import Any, Optional, Callable, cast, TypeAlias
from .registry import get_registry
from .api_types import (
    APIVersion,
    AddonName,
    AddonPath,
    RuntimeExposedHook,
    RuntimeTargetAddon,
    RuntimeTargetFunction,
    SystemKey,
    MY_VERSION,
)

logger = logging.getLogger(__name__)

ExposeAs: TypeAlias = RuntimeExposedHook | tuple | str | bool


def invoke_api(
    owner_path: AddonPath,
    owner_system: SystemKey,
    name: str,
    original_func: Callable,
    *args,
    **kwargs,
):
    """Client-side entry point for API execution. Agnostic wrapper over registry."""
    return get_registry().invoke(
        owner_path, owner_system, name, original_func, *args, **kwargs
    )


@dataclasses.dataclass
class APISystem:
    system_name: SystemKey = None
    _pending_functions: list[dict] = dataclasses.field(default_factory=list)
    _pending_hooks: list[dict] = dataclasses.field(default_factory=list)
    _pending_waiters: list[dict] = dataclasses.field(default_factory=list)
    _pending_exits: list[dict] = dataclasses.field(default_factory=list)
    _pending_expose_module: dict | None = None
    _addon_path: AddonPath | None = None
    # (obj, attr_name, original) for every setattr done by expose_all
    _expose_all_originals: list[tuple[object, str, object]] = dataclasses.field(
        default_factory=list
    )
    _expose_all_visited: set = dataclasses.field(default_factory=set)

    def __post_init__(self):
        if not self._addon_path:
            self._addon_path = get_addon_path()

    def register_contents(self, addon_path: AddonPath):
        self._addon_path = addon_path
        registry = get_registry()

        registry.register_system(addon_path, self.system_name, {})
        for p in self._pending_functions:
            registry.register_function(addon_path, self.system_name, p)
        for p in self._pending_hooks:
            registry.register_hook(addon_path, self.system_name, p)
        for w in self._pending_waiters:
            registry.await_system(addon_path, self.system_name, w)
        for e in self._pending_exits:
            registry.register_exit_callback(addon_path, self.system_name, e)
        if self._pending_expose_module is not None:
            registry.expose_module(
                addon_path, self.system_name, self._pending_expose_module
            )

    def unregister_system(self):
        self._restore_expose_all_originals()
        self._expose_all_visited.clear()
        assert self._addon_path is not None
        get_registry().unregister_system(self._addon_path, self.system_name)

    def _restore_expose_all_originals(self):
        """Reverse every setattr made by expose_all, restoring the class/module to its
        pre-wrap state so a subsequent expose_all (addon reload) works correctly."""
        for obj, attr_name, original in self._expose_all_originals:
            try:
                setattr(obj, attr_name, original)
            except Exception as exc:
                logger.warning(
                    f"expose_all restore failed for {obj!r}.{attr_name}: {exc}"
                )
        self._expose_all_originals.clear()

    def _wrap_func(self, func: Callable, api_name: str):
        """Wraps a function to invoke the API chain when called."""
        system_name = self.system_name
        sig = inspect.signature(func)

        env = {
            "_wrapper_invoke_api": invoke_api,
            "_wrapper_system": self,
            "_wrapper_system_name": system_name,
            "_wrapper_func_name": api_name,
            "_wrapper_func": func,
        }

        params_parts: list[str] = []
        call_parts: list[str] = []
        last_kind: inspect._ParameterKind | None = None

        for name, param in sig.parameters.items():
            # Add / for positional-only transitions
            if (
                last_kind == inspect.Parameter.POSITIONAL_ONLY
                and param.kind != inspect.Parameter.POSITIONAL_ONLY
            ):
                params_parts.append("/")

            # Add * for keyword-only transitions
            if (
                last_kind != inspect.Parameter.KEYWORD_ONLY
                and param.kind == inspect.Parameter.KEYWORD_ONLY
            ):
                # Only add * if there wasn't a *args already
                if not any(
                    p.kind == inspect.Parameter.VAR_POSITIONAL
                    for p in sig.parameters.values()
                ):
                    params_parts.append("*")

            p_str = name
            if param.kind == inspect.Parameter.VAR_POSITIONAL:
                p_str = f"*{name}"
                call_parts.append(f"*{name}")
            elif param.kind == inspect.Parameter.VAR_KEYWORD:
                p_str = f"**{name}"
                call_parts.append(f"**{name}")
            else:
                if param.kind == inspect.Parameter.KEYWORD_ONLY:
                    call_parts.append(f"{name}={name}")
                else:
                    call_parts.append(name)

                if param.default is not inspect.Parameter.empty:
                    env_key = f"_wrapper_default_{name}"
                    env[env_key] = param.default
                    p_str += f"={env_key}"

            params_parts.append(p_str)
            last_kind = param.kind

        if last_kind == inspect.Parameter.POSITIONAL_ONLY:
            params_parts.append("/")

        sig_str = ", ".join(params_parts)
        call_sig_str = ", ".join(call_parts)

        def_str = f"def wrapper({sig_str}): return _wrapper_invoke_api(_wrapper_system._addon_path, _wrapper_system_name, _wrapper_func_name, _wrapper_func, {call_sig_str})"
        exec(def_str, env)

        wrapper = cast(Callable, env["wrapper"])
        functools.update_wrapper(wrapper, func)
        wrapper.__is_api_wrapper__ = True  # type: ignore[attr-defined]

        return wrapper

    def function(
        self,
        name: str | Callable | None = None,
        version: APIVersion = APIVersion(),
        unstable: bool = False,
    ):
        def decorator(func: Callable):
            actual_name = name if isinstance(name, str) else func.__name__
            self._pending_functions.append(
                {
                    "name": actual_name,
                    "func": func,
                    "version": version.to_tuple(),
                    "docs": func.__doc__ or "",
                    "unstable": unstable,
                }
            )

            return self._wrap_func(func, actual_name)

        if callable(name):
            func = name
            name = None
            return decorator(func)

        return decorator

    def hook(
        self,
        target: RuntimeTargetFunction,
        when: str = "before",
        version_constraint: str = "",
        requires_provider: Optional[list[RuntimeTargetAddon]] = None,
        expose_api_as: ExposeAs = True,
        yields_to: Optional[list[RuntimeTargetFunction]] = None,
    ):
        def decorator(func: Callable):
            actual_expose: Optional[RuntimeExposedHook] = None
            if expose_api_as is True:
                actual_expose = RuntimeExposedHook(name=func.__name__, is_unstable=True)
            elif isinstance(expose_api_as, str):
                actual_expose = RuntimeExposedHook(name=expose_api_as, is_unstable=True)
            elif isinstance(expose_api_as, RuntimeExposedHook):
                actual_expose = expose_api_as
            elif isinstance(expose_api_as, tuple):
                assert len(expose_api_as) == 2, "Invalid expose_api_as tuple"
                actual_expose = RuntimeExposedHook(*expose_api_as, is_unstable=True)

            self._pending_hooks.append(
                {
                    "target": target.to_dict(),
                    "func": func,
                    "hook_type": when,
                    "constraint": version_constraint,
                    "yields_to": [y.to_dict() for y in yields_to or []],
                    "requires_provider": [y.to_dict() for y in requires_provider or []],
                    "expose_api_as": actual_expose.to_dict() if actual_expose else None,
                }
            )

            if actual_expose:
                return self._wrap_func(func, actual_expose.name)

            return func

        return decorator

    def override(
        self,
        target: RuntimeTargetFunction,
        version_constraint: str = "",
        yields_to: Optional[list[RuntimeTargetFunction]] = None,
        requires_provider: Optional[list[RuntimeTargetAddon]] = None,
        expose_api_as: ExposeAs = True,
    ):
        return self.hook(
            target,
            "override",
            version_constraint,
            requires_provider,
            expose_api_as,
            yields_to,
        )

    def before(
        self,
        target: RuntimeTargetFunction,
        version_constraint: str = "",
        yields_to: Optional[list[RuntimeTargetFunction]] = None,
        requires_provider: Optional[list[RuntimeTargetAddon]] = None,
        expose_api_as: ExposeAs = True,
    ):
        return self.hook(
            target,
            "before",
            version_constraint,
            requires_provider,
            expose_api_as,
            yields_to,
        )

    def after(
        self,
        target: RuntimeTargetFunction,
        version_constraint: str = "",
        yields_to: Optional[list[RuntimeTargetFunction]] = None,
        requires_provider: Optional[list[RuntimeTargetAddon]] = None,
        expose_api_as: ExposeAs = True,
    ):
        return self.hook(
            target,
            "after",
            version_constraint,
            requires_provider,
            expose_api_as,
            yields_to,
        )

    def on_ready(self, target: RuntimeTargetAddon):
        """Decorator: Run when a specific system in another addon is ready."""

        def decorator(func):
            self._pending_waiters.append(
                {
                    "target": target.to_dict(),
                    "callback_func": func,
                }
            )
            return func

        return decorator

    def on_exit(self, target: RuntimeTargetAddon):
        """
        Decorator: Runs when the connection is broken (either side unregisters).
        """

        def decorator(func):
            self._pending_exits.append(
                {
                    "target": target.to_dict(),
                    "callback_func": func,
                }
            )
            return func

        return decorator

    def finalize_system(self):
        assert self._addon_path is not None
        get_registry().finalize_system(self._addon_path, self.system_name)

    def expose_module(self, module: ModuleType):
        """Stores module so consumers can retrieve it via get_system_module()."""
        self._pending_expose_module = {"module": module}

    def expose_all(
        self,
        target: object,
        unstable: bool = True,
        recursive: bool = True,
        exclude: Optional[list[str]] = None,
        starting_prefix: str = "",
        hide_private: bool = True,
    ):
        """
        Automatically expose all functions and methods within a target module or class.
        By default, sets `unstable=True` to flag these automated endpoints safely.
        exclude_list includes "*blender_api_lib*" by default.

        Every change is recorded in _expose_all_originals
        """
        exclude_list = exclude if exclude else ["*blender_api_lib*"]
        visited_ids = self._expose_all_visited

        base_package = None
        if inspect.ismodule(target):
            base_package = target.__name__.split(".")[0]
        elif hasattr(target, "__module__") and target.__module__:
            base_package = target.__module__.split(".")[0]

        def _safe_wrap(obj, attr_name, api_name, descriptor, member):
            """Wrap one attribute and record the original so it can be restored."""
            try:
                if isinstance(descriptor, classmethod):
                    base_func = descriptor.__func__
                    wrapped = self.function(api_name, unstable=unstable)(base_func)
                    self._expose_all_originals.append((obj, attr_name, descriptor))
                    setattr(obj, attr_name, classmethod(wrapped))
                elif isinstance(descriptor, staticmethod):
                    base_func = descriptor.__func__
                    wrapped = self.function(api_name, unstable=unstable)(base_func)
                    self._expose_all_originals.append((obj, attr_name, descriptor))
                    setattr(obj, attr_name, staticmethod(wrapped))
                elif isinstance(descriptor, property):
                    return  # properties are skipped
                else:
                    wrapped = self.function(api_name, unstable=unstable)(member)
                    self._expose_all_originals.append((obj, attr_name, member))
                    setattr(obj, attr_name, wrapped)
            except (TypeError, AttributeError) as exc:
                logger.warning(f"expose_all could not wrap {obj!r}.{attr_name}: {exc}")

        def _traverse(obj, prefix=""):
            if id(obj) in visited_ids:
                return
            visited_ids.add(id(obj))

            for name, member in inspect.getmembers(obj):
                if name.startswith("_") and hide_private:
                    continue

                full_name = f"{prefix}{name}"
                api_name = f"{starting_prefix}{full_name}"

                if any(fnmatch.fnmatch(api_name, pat) for pat in exclude_list):
                    continue

                if inspect.isfunction(member) or inspect.ismethod(member):
                    if inspect.ismodule(obj):
                        if getattr(member, "__module__", None) != obj.__name__:
                            continue
                    elif inspect.isclass(obj):
                        if name not in obj.__dict__:
                            continue

                    # Skip already-wrapped API functions — they belong to a previous
                    # registration that wasn't cleaned up, or are already exposed
                    # via a different path on this system.
                    if getattr(member, "__is_api_wrapper__", False):
                        logger.warning(
                            f"expose_all: {obj!r}.{name} is already an API wrapper "
                            "and will be skipped. Did a previous unregister fail to "
                            "restore the original?"
                        )
                        continue

                    descriptor = obj.__dict__.get(name, member)
                    _safe_wrap(obj, name, api_name, descriptor, member)

                elif inspect.isclass(member) and recursive:
                    # Skip imported classes in modules
                    if (
                        inspect.ismodule(obj)
                        and getattr(member, "__module__", None) != obj.__name__
                    ):
                        continue

                    _traverse(member, prefix=f"{full_name}.")

                elif inspect.ismodule(member) and recursive:
                    # Only traverse submodules that belong to the same base package
                    if base_package and getattr(member, "__name__", "").startswith(
                        base_package
                    ):
                        _traverse(member, prefix=f"{full_name}.")

        _traverse(target)
        return target

    def get_override(self, name: str):
        assert self._addon_path is not None
        return get_registry().get_active_implementation(
            self._addon_path, self.system_name, name
        )


def get_addon_path() -> AddonPath:
    if __package__:
        return __package__.split(".")[0]
    return "unknown_addon"


def get_system_module(name: AddonName, system_name: SystemKey):
    return get_registry().get_system_module(name, target_system_name=system_name)


@dataclasses.dataclass
class APIAddon:
    name: AddonName
    bl_info: dict[str, Any]
    addon_path: AddonPath | None = None
    systems: dict[SystemKey, APISystem] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        if not self.addon_path:
            self.addon_path = get_addon_path()

    def register_addon(self):
        registry = get_registry()
        assert self.addon_path is not None
        registry.register_addon(
            self.addon_path, self.name, MY_VERSION, {"bl_info": self.bl_info}
        )

    def unregister_addon(self):
        for system in self.systems.values():
            system.unregister_system()
        registry = get_registry()
        assert self.addon_path is not None
        registry.unregister_addon(self.addon_path)

    def register_system(self, system: APISystem):
        self.systems[system.system_name] = system

        assert self.addon_path is not None
        logger.info(f"Registering {self.addon_path}:{system.system_name}")
        system.register_contents(self.addon_path)
        return system

    def unregister_system(self, system_name: SystemKey):
        system = self.systems.pop(system_name, None)
        if system is None:
            return
        system.unregister_system()


SYSTEMS: dict[SystemKey, APISystem] = {}


def get_or_create_system(system_name: SystemKey):
    system_name = tuple(system_name) if system_name else None
    return SYSTEMS.setdefault(system_name, APISystem(system_name))


API_ADDON_SINGLETON: Optional[APIAddon] = None


def register_addon(name: str, bl_info: dict):
    global API_ADDON_SINGLETON
    if API_ADDON_SINGLETON is None:
        API_ADDON_SINGLETON = APIAddon(name, bl_info)
        API_ADDON_SINGLETON.register_addon()
    return API_ADDON_SINGLETON


def unregister_addon():
    global API_ADDON_SINGLETON, SYSTEMS
    if API_ADDON_SINGLETON is None:
        return
    API_ADDON_SINGLETON.unregister_addon()
    API_ADDON_SINGLETON = None
    SYSTEMS.clear()


def register_system(system: SystemKey | APISystem):
    global API_ADDON_SINGLETON, SYSTEMS
    if API_ADDON_SINGLETON is None:
        logger.error("API Error: Register addon first")
        return None

    if not isinstance(system, APISystem):
        system = get_or_create_system(system)

    return API_ADDON_SINGLETON.register_system(system)  # type: ignore[arg-type]


def unregister_system(system: SystemKey | APISystem):
    global API_ADDON_SINGLETON, SYSTEMS
    if API_ADDON_SINGLETON is None:
        return None

    if not isinstance(system, APISystem):
        system_obj = SYSTEMS.get(system)
    else:
        system_obj = system

    if system_obj is None:
        return

    API_ADDON_SINGLETON.unregister_system(system_obj.system_name)

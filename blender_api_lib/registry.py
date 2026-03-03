try:
    import bpy

    HAS_BPY = hasattr(bpy, "types")
except ImportError:
    HAS_BPY = False

import logging
import inspect
import sys
import dataclasses
from types import ModuleType
from typing import NamedTuple, Optional, Callable

from .api_types import (
    APIVersion,
    AddonPath,
    AddonName,
    RuntimeExposedHook,
    RuntimeFunction,
    RuntimeHook,
    RuntimeSystem,
    RuntimeTargetAddon,
    RuntimeTargetFunction,
    RuntimeWaiter,
    RuntimeAddon,
    HookType,
    APIContext,
    MY_VERSION,
    SystemKey,
    RuntimeExecutionChain,
    RuntimeExecutionNode,
)

logger = logging.getLogger(__name__)

_GLOBAL_KEY = "blender_addon_api_shared_registry"
KNOWN_VERSIONS = [1]


if HAS_BPY:

    class API_OT_ToggleUISection(bpy.types.Operator):
        """Toggles the visibility of a registry section"""

        bl_idname = "api.toggle_ui_section"
        bl_label = "Toggle Section"

        key: bpy.props.StringProperty  # type: ignore[misc]

        def execute(self, context):
            from .registry import get_registry

            get_registry().toggle_expanded(self.key)
            return {"FINISHED"}


@dataclasses.dataclass
class APIRegistry:
    """Central registry for managing API functions, hooks, and lifecycles across addons."""

    _addons: dict[AddonPath, dict] = dataclasses.field(default_factory=dict)
    _registered_ui: bool = False
    _ui_toggles: dict[str, bool] = dataclasses.field(default_factory=dict)
    _runtime_addons: Optional[dict[AddonPath, RuntimeAddon]] = None

    _invocation_cache: dict[tuple[str, SystemKey, str], tuple] = dataclasses.field(
        default_factory=dict
    )

    @property
    def instance_version(self):
        return MY_VERSION

    def invalidate_cache(self):
        self._invocation_cache.clear()
        self._runtime_addons = None

    def register_bpy_ui_props(self):
        assert HAS_BPY, "Blender Python API not found"

        bpy.utils.register_class(API_OT_ToggleUISection)
        self._registered_ui = True

    def unregister_bpy_ui_props(self):
        assert HAS_BPY, "Blender Python API not found"
        if self._registered_ui:
            bpy.utils.unregister_class(API_OT_ToggleUISection)
            self._registered_ui = False

    def toggle_expanded(self, key: str):
        assert HAS_BPY, "Blender Python API not found"
        self._ui_toggles[key] = not self._ui_toggles.get(key, True)

    # --- Data Parsing Methods ---

    def _create_runtime_function(self, func_data: dict):
        for key in {"name", "func", "version"}:
            if key not in func_data:
                raise ValueError(f"Missing key in function: {key}")
        return RuntimeFunction(
            name=func_data["name"],
            func=func_data["func"],
            version=APIVersion.from_tuple(func_data["version"]),
            docs=func_data.get("docs", ""),
            is_unstable=func_data.get("unstable", False),
        )

    def _create_runtime_hook(self, hook_data: dict, system: RuntimeSystem):
        for key in {"target", "func", "hook_type"}:
            assert key in hook_data, f"Missing key in hook: {key}"

        yields_to = []
        for y in hook_data.get("yields_to", []):
            yields_to.append(RuntimeTargetFunction.from_dict(y))

        expose_api_as = hook_data.get("expose_api_as")
        if expose_api_as is not None:
            expose_api_as = RuntimeExposedHook.from_dict(expose_api_as)

        return RuntimeHook(
            system=system,
            target=RuntimeTargetFunction.from_dict(hook_data["target"]),
            func=hook_data["func"],
            hook_type=HookType(hook_data["hook_type"]),
            version_constraint=hook_data.get("constraint", ">=1.0"),
            yields_to=yields_to,
            requires_provider=[
                RuntimeTargetAddon.from_dict(p)
                for p in hook_data.get("requires_provider", [])
            ],
            expose_api_as=expose_api_as,
        )

    def _create_runtime_waiter(self, waiter_data: dict):
        if "callback_func" not in waiter_data:
            raise ValueError("Missing key in waiter: callback_func")
        return RuntimeWaiter(callback_func=waiter_data["callback_func"])

    def _create_runtime_waiters(self, target_waiters: dict):
        runtime_waiters = {}
        for target, waiters in target_waiters.items():
            target = RuntimeTargetAddon.from_dict(dict(target))
            runtime_waiters[target] = [self._create_runtime_waiter(w) for w in waiters]
        return runtime_waiters

    def _create_runtime_system(
        self, system_data: dict, name: SystemKey, addon: RuntimeAddon
    ):
        system = RuntimeSystem(
            addon=addon, name=name, ready=system_data.get("ready", False)
        )
        system.module = (system_data.get("module") or {}).get("module")
        for func_data in system_data.get("functions", {}).values():
            func = self._create_runtime_function(func_data)
            system.functions[func.name] = func

        for hook_data in system_data.get("hooks", []):
            system.hooks.append(self._create_runtime_hook(hook_data, system))

        system.on_ready = self._create_runtime_waiters(system_data.get("on_ready", {}))
        system.on_exit = self._create_runtime_waiters(system_data.get("on_exit", {}))

        return system

    def _create_runtime_addon(self, addon_data: dict, path: AddonPath):
        for key in {"name", "instance_version"}:
            if key not in addon_data:
                raise ValueError(f"Missing key in addon: {key}")

        addon = RuntimeAddon(
            name=addon_data["name"],
            path=path,
            instance_version=addon_data["instance_version"],
            bl_info=addon_data.get("info", {}).get("bl_info", {}),
        )

        for system_name, system_data in addon_data.get("systems", {}).items():
            addon.systems[system_name] = self._create_runtime_system(
                system_data, system_name, addon
            )

        return addon

    def _create_runtime_addons(self):
        """Parses ABI-safe raw dictionaries into version-safe dataclasses dynamically."""
        if self._runtime_addons is None:
            self._runtime_addons = {
                path: self._create_runtime_addon(addon_data, path)
                for path, addon_data in self._addons.items()
            }
        return self._runtime_addons

    # --- Iterators & Abstractions ---

    def _iter_systems(self):
        """Yields flat tuples of (path, raw_addon, system_name, raw_system)."""
        for path, addon in self._addons.items():
            for sys_name, system in addon.get("systems", {}).items():
                yield path, addon, sys_name, system

    def _iter_runtime_systems(self):
        """Yields flat tuples of (path, RuntimeAddon, system_name, RuntimeSystem)."""
        for path, addon in self._create_runtime_addons().items():
            for sys_name, system in addon.systems.items():
                yield system

    def _iter_runtime_hooks(self):
        """Yields flat tuples of (path, RuntimeAddon, system_name, RuntimeHook)."""
        for system in self._iter_runtime_systems():
            for hook in system.hooks:
                yield hook

    def _has_runtime_function(self, target: RuntimeTargetFunction):
        """Checks if a target function strictly exists in the current registry."""
        return self._get_target_function(target)[0] is not None

    def _match_hook_to_chain(self, hook: RuntimeHook, chain_targets: list):
        """Finds the depth and target info if the given hook targets a step in the execution chain."""
        for depth, (target, target_func_name, target_version) in enumerate(
            chain_targets
        ):
            if (
                hook.target.function == target_func_name
                and hook.target.addon == target.addon
                and hook.target.system == target.system
            ):
                return depth, target, target_func_name, target_version
        return None

    # --- Accessor Methods ---

    def _get_addons_by_name(self, name: AddonName):
        return [path for path, data in self._addons.items() if data["name"] == name]

    def _get_addon(self, path: AddonPath, error_missing_addon: bool = True):
        if path in self._addons:
            return self._addons[path]
        if error_missing_addon:
            raise KeyError(f"Addon {path} not found")
        return None

    def _get_addons(self, name: AddonName, error_missing_addon: bool = True):
        paths = self._get_addons_by_name(name)
        if not paths and error_missing_addon:
            raise KeyError(f"Addon {name} not found")
        return {p: self._addons[p] for p in paths}

    def _get_system(
        self,
        addon_path: AddonPath,
        system_name: SystemKey,
        error_missing_addon: bool = True,
        error_missing_system: bool = True,
    ):
        addon = self._get_addon(addon_path, error_missing_addon)
        if addon is not None:
            systems: dict[SystemKey, dict] = addon.get("systems")
            assert systems is not None, "Addon must have systems"
            if system_name in systems:
                return systems[system_name]
            if error_missing_system:
                raise KeyError(f"System {system_name} not found in {addon_path}")
        return None

    def _get_systems(
        self,
        addon_name: AddonName,
        system_name: SystemKey,
        error_missing_addon: bool = True,
        error_missing_system: bool = True,
    ):
        systems: dict[tuple[AddonPath, SystemKey], dict] = {}
        for path, addon in self._get_addons(addon_name, error_missing_addon).items():
            addon_systems = addon.get("systems")
            assert addon_systems is not None, "Addon must have systems"
            if system_name in addon_systems:
                systems[(path, system_name)] = addon_systems[system_name]
            elif error_missing_system:
                raise KeyError(f"System {system_name} not found in {path}")
        return systems

    def _get_waiters(
        self, addon_path: AddonPath, system_name: SystemKey, on_ready: bool = True
    ):
        """Yields tuples of (addon dict, waiter info dict) for the given system."""
        event_key = "on_ready" if on_ready else "on_exit"
        addon_name = self._get_addon(addon_path)["name"]

        for path, addon_data, sys_name, system_data in self._iter_systems():
            for target, infos in system_data.get(event_key, {}).items():
                target = RuntimeTargetAddon.from_dict(dict(target))
                if target.addon == addon_name and target.system == system_name:
                    yield from ((addon_data, info) for info in infos)

    def _get_runtime_addon(self, path: AddonPath, error_missing_addon: bool = True):
        addons = self._create_runtime_addons()
        if path in addons:
            return addons[path]
        if error_missing_addon:
            raise KeyError(f"Addon {path} not found")
        return None

    def _get_runtime_addons_by_name(
        self, name: AddonName, error_missing_addon: bool = True
    ):
        matches = {
            p: a for p, a in self._create_runtime_addons().items() if a.name == name
        }
        if not matches and error_missing_addon:
            raise KeyError(f"Addon {name} not found")
        return matches

    def _get_runtime_system(
        self,
        addon_path: AddonPath,
        system_name: SystemKey,
        error_missing_addon: bool = True,
        error_missing_system: bool = True,
    ):
        addon = self._get_runtime_addon(addon_path, error_missing_addon)
        if addon is not None:
            if system_name in addon.systems:
                return addon.systems[system_name]
            if error_missing_system:
                raise KeyError(f"System {system_name} not found in {addon_path}")
        return None

    def _get_runtime_systems(
        self,
        addon_name: AddonName,
        system_name: SystemKey,
        error_missing_addon: bool = True,
        error_missing_system: bool = True,
    ):
        systems: list[RuntimeSystem] = []
        for path, addon in self._get_runtime_addons_by_name(
            addon_name, error_missing_addon
        ).items():
            if system_name in addon.systems:
                systems.append(addon.systems[system_name])
            elif error_missing_system:
                raise KeyError(f"System {system_name} not found in {path}")
        return systems

    def _get_runtime_waiters(
        self, addon_name: AddonName, system_name: SystemKey, on_ready: bool = True
    ):
        """Yields tuples of (RuntimeAddon, RuntimeWaiter) for the given target system."""
        target_key = RuntimeTargetAddon(addon_name, system_name)
        for system in self._iter_runtime_systems():
            waiter_map = system.on_ready if on_ready else system.on_exit
            if target_key in waiter_map:
                yield from ((system.addon, waiter) for waiter in waiter_map[target_key])

    # --- Registration Methods ---

    def register_addon(
        self, path: AddonPath, name: AddonName, instance_version: int, info: dict
    ):
        if path in self._addons:
            old_name = self._addons[path]["name"]
            if old_name and old_name != name:
                logger.info(f"API addon {path} changing name from {old_name} to {name}")
            else:
                logger.info(f"API addon {path} already registered. Re-registering.")

        self._addons[path] = {
            "name": name,
            "instance_version": instance_version,
            "info": info,
            "systems": {},
            "ready": False,
        }
        self.invalidate_cache()

    def register_system(
        self, addon_path: AddonPath, system_name: SystemKey, info: dict
    ):
        """Registers a new system for a registered addon."""
        if self._get_system(addon_path, system_name, error_missing_system=False):
            logger.warning(
                f"System {addon_path}:{system_name} already registered. Re-registering."
            )

        addon = self._get_addon(addon_path)
        addon["systems"][system_name] = {
            "module": None,
            "functions": {},
            "hooks": [],
            "ready": False,
            "on_ready": {},
            "on_exit": {},
            "info": info,
        }
        self.invalidate_cache()

    def register_function(
        self, addon_path: AddonPath, system_name: SystemKey, info: dict
    ):
        """Registers an API function."""
        assert "name" in info, "API function must have a name"
        assert "func" in info, "API function must have a func"
        assert "version" in info, "API function must have a version"

        system_data = self._get_system(addon_path, system_name)
        system_data["functions"][info["name"]] = info
        self.invalidate_cache()

    def register_hook(self, addon_path: AddonPath, system_name: SystemKey, info: dict):
        """Registers an API hook."""
        assert "func" in info, "API hook must have a function"
        assert "target" in info, "API hook must have a target"

        system_data = self._get_system(addon_path, system_name)
        system_data["hooks"].append(info)

        self.invalidate_cache()

    # --- Lifecycle Methods ---

    def await_system(self, addon_path: AddonPath, system_name: SystemKey, info: dict):
        """Registers a listener for system readiness. Evaluates immediately if already ready."""
        for key in {"target", "callback_func"}:
            assert key in info, f"Missing key in await_system: {key}"

        callback = info["callback_func"]
        target = RuntimeTargetAddon.from_dict(info["target"])

        system_data = self._get_system(addon_path, system_name)
        system_data["on_ready"].setdefault(
            tuple(sorted(info["target"].items())), []
        ).append(info)

        addons = self._get_systems(
            target.addon,
            target.system,
            error_missing_addon=False,
            error_missing_system=False,
        )
        for _, system in addons.items():
            if system.get("ready"):
                try:
                    callback()
                except Exception as exception:
                    logger.error(f"Error in immediate callback: {exception}")

    def register_exit_callback(
        self, addon_path: AddonPath, system_name: SystemKey, info: dict
    ):
        """Registers a listener for system exit."""
        for key in {"target", "callback_func"}:
            assert key in info, f"Exit callback missing required key: {key}"

        system_data = self._get_system(addon_path, system_name)
        system_data["on_exit"].setdefault(
            tuple(sorted(info["target"].items())), []
        ).append(info)

    def finalize_system(self, addon_path: AddonPath, system_name: SystemKey):
        """Marks a system as ready and triggers waiting callbacks."""
        system_data = self._get_system(addon_path, system_name)
        if system_data.get("ready"):
            logger.info(f"System '{addon_path}:{system_name}' already finalized.")
            return

        system_data["ready"] = True
        logger.info(f"System '{addon_path}:{system_name}' is ready.")
        self.invalidate_cache()

        for _, info in self._get_waiters(addon_path, system_name, on_ready=True):
            try:
                info["callback_func"]()
            except Exception as exception:
                logger.exception(f"Error in on_ready callback: {exception}")

    def unregister_system(self, addon_path: AddonPath, system_name: SystemKey):
        """Unregisters a specific system and triggers its exit callbacks."""
        if addon_path not in self._addons:
            return

        addon_systems = self._addons[addon_path]["systems"]
        if system_name in addon_systems:
            for _, info in self._get_waiters(addon_path, system_name, on_ready=False):
                try:
                    info["callback_func"]()
                except Exception as exception:
                    logger.error(f"Error in on_exit callback: {exception}")

            del addon_systems[system_name]
            logger.info(f"System {addon_path}:{system_name} unregistered and removed.")

        self.invalidate_cache()

    def unregister_addon(self, path: AddonPath):
        """Fully unregisters an addon and its systems."""
        if path not in self._addons:
            return

        for system_name in list(self._addons[path].get("systems", {}).keys()):
            self.unregister_system(path, system_name)

        del self._addons[path]
        logger.info(f"API Addon {path} fully unregistered.")
        self.invalidate_cache()

    # Module stuff

    def expose_module(self, path: AddonPath, system_name: SystemKey, info: dict):
        assert "module" in info, "Missing module in expose_module"
        system = self._get_system(path, system_name)
        system["module"] = info

    def get_system_module(
        self,
        name: AddonName | None = None,
        path: AddonPath | None = None,
        target_system_name: SystemKey | None = None,
    ):
        """
        Returns the module defined by its system and defined under its display name.
        The host addon must have passed module=sys.modules[__name__]
        """
        assert name is not None or path is not None, "No name or path"
        assert name is None or path is None, "Name or path"

        if name is not None:
            addon_names = self._get_addons_by_name(name)
            addons = [self._get_runtime_addon(p) for p in addon_names]
            if len(addons) == 0:
                raise RuntimeError(f"Addon {name} not found")
            if len(addons) > 2:
                logger.warning(f"Multiple addons under the same name {name}")
        else:
            addons = [self._get_runtime_addon(path)]

        found_system = False
        for addon_data in addons:
            system = addon_data.systems.get(target_system_name)
            if system is not None:
                found_system = True
                if system.module is not None:
                    return system.module

        if found_system:
            logger.warning(
                f"Addon '{name or path}' and system '{target_system_name}' are registered but did not expose a module."
            )
        else:
            logger.warning(
                f"Addon '{name or path}' is registered but not system '{target_system_name}'"
            )
        return None

    # --- Invocation & Execution ---

    def _get_ctx_mode(self, func: Callable):
        """Determines how 'ctx' should be passed to a function. 0: None, 1: Positional, 2: Kwarg."""
        try:
            sig = inspect.signature(func)
        except ValueError:
            return 0
        if "ctx" in sig.parameters:
            param = sig.parameters["ctx"]
            if (
                param.annotation == inspect.Parameter.empty
                or getattr(param.annotation, "__name__", None) != "APIContext"
            ):
                return 0

            if len(sig.parameters) != 1:
                logger.warning(
                    f"Function '{func.__name__}' has 'ctx' parameter but has other parameters"
                )
                return 0

            if (
                param.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
                and list(sig.parameters.keys())[0] == "ctx"
            ):
                return 1
            return 2
        return 0

    def _call_with_context(
        self,
        ctx_mode: int,
        func: Callable,
        ctx: APIContext,
        args: list,
        kwargs: dict,
    ):
        """Invokes a function with the appropriate context passing mode."""
        if ctx_mode == 1:
            return func(ctx)
        elif ctx_mode == 2:
            return func(ctx=ctx)
        else:
            return func(*args, **kwargs)

    def _get_target_function(self, target: RuntimeTargetFunction):
        """Resolves a target callable from the registry, checking base functions and exposed hooks."""
        target_addons = self._get_runtime_addons_by_name(
            target.addon, error_missing_addon=False
        )
        if not target_addons:
            return None, "Target addon not found"

        found_system = False
        for addon in target_addons.values():
            system = addon.systems.get(target.system)
            if not system:
                continue
            found_system = True

            if target.function in system.functions:
                return system.functions[target.function].func, None

            for h in system.hooks:
                if h.expose_api_as and (
                    h.expose_api_as.name == target.function
                    and h.expose_api_as.version.match(target.version_constraint)
                ):
                    return h.func, None
        if not found_system:
            return None, "Target system not found"
        return None, "Target function not found"

    def _get_hook_validation_error(self, hook: RuntimeHook):
        """Strictly validates a hook's argument count and variadic capacity against its target."""
        target_func, error = self._get_target_function(hook.target)
        if error:
            return error

        try:
            target_sig = inspect.signature(target_func)
            hook_sig = inspect.signature(hook.func)
        except ValueError:
            return "Invalid signature"

        if self._get_ctx_mode(hook.func) != 0:
            return None  # if ctx is available, don't validate

        target_params = [p for n, p in target_sig.parameters.items()]
        hook_params = [p for n, p in hook_sig.parameters.items()]

        hook_has_var_args = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL for p in hook_params
        )
        hook_has_var_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in hook_params
        )
        target_has_var_args = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL for p in target_params
        )
        target_has_var_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in target_params
        )

        target_pos = [
            p
            for p in target_params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        hook_pos = [
            p
            for p in hook_params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]

        if len(hook_pos) < len(target_pos) and not hook_has_var_args:
            return f"Expected {len(target_pos)} positional args, got {len(hook_pos)}"

        hook_required_pos = [
            p for p in hook_pos if p.default == inspect.Parameter.empty
        ]
        if len(hook_required_pos) > len(target_pos) and not target_has_var_args:
            return f"Requires {len(hook_required_pos)} positional args, target provides max {len(target_pos)}"

        hook_required_kw_only = [
            p
            for p in hook_params
            if p.kind == inspect.Parameter.KEYWORD_ONLY
            and p.default == inspect.Parameter.empty
        ]
        if not target_has_var_kwargs:
            target_names = {p.name for p in target_params}
            for hk in hook_required_kw_only:
                if hk.name not in target_names:
                    return (
                        f"Requires keyword argument '{hk.name}' not provided by target"
                    )

        target_kw_only = [
            p for p in target_params if p.kind == inspect.Parameter.KEYWORD_ONLY
        ]
        if not hook_has_var_kwargs:
            hook_names = {p.name for p in hook_params}
            for tk in target_kw_only:
                if tk.name not in hook_names:
                    return f"Missing required keyword argument: '{tk.name}'"

        return None

    def _is_yielded(self, yields_to: list[RuntimeTargetFunction]):
        """Checks if a hook is blocked by an existing addon."""
        return any(self._has_runtime_function(target) for target in yields_to)

    def _meets_required(self, required: list[RuntimeTargetAddon]):
        if not required:
            return True
        return all(
            len(self._get_runtime_systems(addon.name, addon.system, False, False)) > 0
            for addon in required
        )

    def _check_if_hook_targets(
        self, active: RuntimeExecutionNode, hook: RuntimeHook
    ) -> tuple[str | None, bool]:
        if (
            hook.target.function == active.name
            and hook.target.addon == active.system.addon.name
            and hook.target.system == active.system.name
            and not self._is_yielded(hook.yields_to)
            and self._meets_required(hook.requires_provider)
            and (active.version.match(hook.version_constraint))
        ):
            return self._get_hook_validation_error(hook), True

        return None, False

    def get_active_implementation(
        self, owner_path: AddonPath, owner_system: SystemKey, name: str
    ):
        """Returns the active implementation and its owner for a given API function, if overridden."""
        system = self._get_runtime_system(
            owner_path, owner_system, error_missing_system=False
        )
        if not system or name not in system.functions:
            raise KeyError(
                f"API Function '{name}' not found in {owner_path}:{owner_system}"
            )

        original_func = system.functions[name].func

        chain, errors = self._start_build_execution_chain(
            owner_path, owner_system, name, original_func
        )

        for error in errors:
            logger.error(f"Error resolving override for {name}: {error}")

        return (
            chain.main.func.__name__ or chain.main.name,
            chain.main.system.name,
            chain.main.system.addon.name,
        )

    def _resolve_override(self, active: RuntimeExecutionNode):
        """Finds all valid overrides for a given target API function using runtime structures."""
        overrides: list[RuntimeExecutionNode] = []
        errors: list[str] = []

        for hook in self._iter_runtime_hooks():
            if hook.system.addon.path == active.system.addon.path:
                continue

            if hook.hook_type != HookType.OVERRIDE:
                continue
            result = self._check_if_hook_targets(active, hook)
            if result[1]:
                if result[0] is None:
                    if hook.expose_api_as is None:
                        node = RuntimeExecutionNode(hook.func, hook.system)
                    else:
                        node = RuntimeExecutionNode(
                            hook.func,
                            hook.system,
                            hook.expose_api_as.name,
                            hook.expose_api_as.version,
                        )
                    overrides.append(node)
                else:
                    errors.append(result[0])

        if overrides:
            if len(overrides) > 1:
                logger.warning("Multiple overrides per func call. Using first.")
            return overrides[0], errors

        return None, errors

    def _resolve_before_after_hooks(
        self,
        chain: RuntimeExecutionChain,
        active: RuntimeExecutionNode,
        errors: list[str],
    ):
        for hook in self._iter_runtime_hooks():
            if hook.hook_type not in {HookType.BEFORE, HookType.AFTER}:
                continue
            hook_errors = []
            result = self._check_if_hook_targets(active, hook)
            if result[0] is not None:
                hook_errors.append(result[0])
            if result[1]:
                if hook.expose_api_as is None:
                    main = RuntimeExecutionNode(hook.func, hook.system)
                else:
                    main = RuntimeExecutionNode(
                        hook.func,
                        hook.system,
                        hook.expose_api_as.name,
                        hook.expose_api_as.version,
                    )
                new_chain = RuntimeExecutionChain(main=main)
                if hook.expose_api_as is not None:
                    self._build_execution_chain(new_chain, hook_errors)
                chain.add_hook(hook.hook_type, new_chain)
            for error in hook_errors:
                errors.append(f'In hook "{hook.func.__name__}": {error}')

    def _build_execution_chain(self, chain: RuntimeExecutionChain, errors: list[str]):
        active = chain.main

        self._resolve_before_after_hooks(chain, active, errors)

        override, override_errors = self._resolve_override(active)
        errors.extend(override_errors)
        if override is not None:
            if override == chain.main or any(
                old.main == override for old in chain.old_main
            ):
                logger.warning(
                    f"Override {override} is already in the execution chain. Probably a cyclic override."
                )
                return  # Prevent infinite recursion!
            chain.change_main(override)
            self._build_execution_chain(chain, errors)

    def _start_build_execution_chain(
        self,
        owner_path: AddonPath,
        owner_system: SystemKey,
        func_name: str,
        original_func: Callable,
    ):
        sys = self._get_runtime_system(owner_path, owner_system)
        active = RuntimeExecutionNode(
            original_func, sys, func_name, sys.functions[func_name].version
        )

        chain = RuntimeExecutionChain(main=active)
        errors: list[str] = []
        self._build_execution_chain(chain, errors)
        return chain, errors

    def _flatten_execution_chain(
        self, chain: RuntimeExecutionChain, is_root: bool = True
    ) -> list[tuple[RuntimeExecutionNode, bool]]:
        """Recursively fully flattens an execution chain into an ordered list of execution node tuples."""
        nodes = []

        for old in chain.old_main:
            for b in old.before:
                nodes.extend(self._flatten_execution_chain(b, is_root=False))

        for b in chain.before:
            nodes.extend(self._flatten_execution_chain(b, is_root=False))

        nodes.append((chain.main, is_root))

        for a in chain.after:
            nodes.extend(self._flatten_execution_chain(a, is_root=False))

        for old in reversed(chain.old_main):
            for a in old.after:
                nodes.extend(self._flatten_execution_chain(a, is_root=False))

        return nodes

    def _get_execution_step(self, node: RuntimeExecutionNode, is_root: bool):
        return (
            node.func,
            self._get_ctx_mode(node.func),
            node.name or node.func.__name__,
            node.system.addon.name,
            node.system.name,
            is_root,
        )

    def invoke(
        self,
        owner_path: AddonPath,
        owner_system: SystemKey,
        name: str,
        original_func: Callable,
        *args,
        **kwargs,
    ):
        """Invokes an API function, executing any registered hooks sequentially along a flattened execution chain."""
        cache_key = (owner_path, owner_system, name)

        cached = self._invocation_cache.get(cache_key)
        if cached is None:
            chain, errors = self._start_build_execution_chain(
                owner_path, owner_system, name, original_func
            )

            flat_nodes = self._flatten_execution_chain(chain, is_root=True)
            steps = [self._get_execution_step(n, is_root) for n, is_root in flat_nodes]

            # Find root main to extract authoritative bound arguments context
            main_step = next((s for s in steps if s[5]), None)
            try:
                sig = inspect.signature(main_step[0]) if main_step else None
            except ValueError:
                sig = None

            cached = (steps, errors, sig)
            self._invocation_cache[cache_key] = cached

        steps, errors, sig = cached
        for error in errors:
            logger.error(error)

        try:
            if sig:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                arguments = bound.arguments
            else:
                arguments = {}
        except TypeError:
            arguments = {}

        ctx = APIContext(
            api_name=name,
            calling_addon=owner_path,
            args=list(args),
            kwargs=kwargs.copy(),
            arguments=arguments,
        )

        for func, ctx_mode, step_name, addon_name, system_name, is_main in steps:
            # Update APIContext to make the active execution block fully aware of its environment
            ctx.active_addon = addon_name
            ctx.active_system = system_name
            ctx.active_function = step_name
            ctx.is_main = is_main

            try:
                res = self._call_with_context(ctx_mode, func, ctx, ctx.args, ctx.kwargs)
                if is_main:
                    ctx.set_data("result", res)
            except Exception as exception:
                phase_name = "active" if is_main else "hook"
                raise RuntimeError(
                    f"Exception in {phase_name} function {step_name} of {addon_name}"
                ) from exception

        return ctx.get_data("result")

    # --- UI Drawing Methods ---

    def _format_system_name(self, system_name: SystemKey):
        return ".".join(system_name) if system_name else ""

    def _draw_chain_recursive(
        self, layout, chain: RuntimeExecutionChain, depth: int = 0, role: str = "MAIN"
    ):
        prefix = "  " * depth

        if role == "BEFORE":
            label_prefix = "◀ Before: "
        elif role == "AFTER":
            label_prefix = "▶ After: "
        else:
            label_prefix = "◆ Override: " if depth > 0 else "● Active: "

        for old in chain.old_main:
            for b in old.before:
                self._draw_chain_recursive(layout, b, depth + 1, "BEFORE")

            sys_str = self._format_system_name(old.main.system.name)
            version = "" if old.main.version.is_none else f" (v{old.main.version})"
            layout.label(
                text=f"{prefix} ∅ [Replaced] {old.main.system.addon.name}:{sys_str}.{old.main.name or old.main.func.__name__}{version}",
            )

        for b in chain.before:
            self._draw_chain_recursive(layout, b, depth + 1, "BEFORE")

        node = chain.main
        sys_str = self._format_system_name(node.system.name)
        version = "" if node.version.is_none else f" (v{node.version})"
        layout.label(
            text=f"{prefix}{label_prefix}{node.system.addon.name}:{sys_str}.{node.name or node.func.__name__}{version}"
        )

        for a in chain.after:
            self._draw_chain_recursive(layout, a, depth + 1, "AFTER")

        for old in reversed(chain.old_main):
            for a in old.after:
                self._draw_chain_recursive(layout, a, depth + 1, "AFTER")

    def draw_tab(
        self, layout: "bpy.types.UILayout", key: str, text: Optional[str] = None
    ):
        state = self._ui_toggles.get(key, True)
        left_side = layout.row(align=True)
        left_side.alignment = "LEFT"
        op = left_side.operator(
            API_OT_ToggleUISection.bl_idname,
            text=text,
            icon="TRIA_DOWN" if state else "TRIA_RIGHT",
            emboss=False,
        )
        op.key = key
        return state

    def _draw_execution_chain(
        self,
        layout,
        owner_path: AddonPath,
        system_name: SystemKey,
        func: RuntimeFunction,
    ):
        """Draws the detailed hook and override execution chain for a specific function."""
        key = f"chain.{owner_path}.{system_name}.{func.name}"
        box = layout.box()
        row = box.row()
        version = "" if func.version.is_none else f" (v{func.version})"

        try:
            chain, errors = self._start_build_execution_chain(
                owner_path, system_name, func.name, func.func
            )
        except Exception as exception:
            chain, errors = RuntimeExecutionChain(), [
                "Error resolving chain: {exception}"
            ]

        nothing_to_see = (
            not chain.before and not chain.after and not chain.old_main and not errors
        )
        if errors:
            row.alert = True

        if nothing_to_see:
            result = False
            row.label(text=f"{func.name}{version}")
        else:
            result = self.draw_tab(row, key, text=f"{func.name}{version}")
        if func.is_unstable:
            unstable_row = row.row()
            unstable_row.alignment = "RIGHT"
            unstable_row.label(text="UNSTABLE", icon="ERROR")
        if not result:
            return

        for error in errors:
            error_layout = box.row()
            error_layout.alert = True
            error_layout.label(text=error, icon="ERROR")

        chain_col = box.column(align=True)
        self._draw_chain_recursive(chain_col, chain)

    def _draw_system_functions(
        self,
        layout,
        addon_path: AddonPath,
        system_name: SystemKey,
        system: RuntimeSystem,
    ):
        if not system.functions:
            return
        func_col = layout.column()
        func_col.label(text="Execution Chains:")
        for func in system.functions.values():
            self._draw_execution_chain(func_col, addon_path, system_name, func)

    def _draw_system_hooks(self, layout, system: RuntimeSystem):
        if not system.hooks:
            return
        hook_col = layout.column()
        hook_col.label(text="Registered Hooks:", icon="LINKED")
        for hook in system.hooks:
            target_sys_str = self._format_system_name(hook.target.system)
            error = self._get_hook_validation_error(hook)

            key = (
                f"hook.{hook.system.name}.{hook.system.addon.name}.{hook.func.__name__}"
            )
            hook_icon = {
                HookType.BEFORE: "◁",
                HookType.AFTER: "▷",
                HookType.OVERRIDE: "●",
            }[hook.hook_type]

            hook_text = f"{hook_icon} {hook.func.__name__} ({hook.target.function})"

            box = hook_col.box().column()
            op_layout = box.row()
            op_layout.alert = error is not None
            if not self.draw_tab(op_layout, key, hook_text):
                continue

            box.label(
                text=f"Target System: {hook.target.addon}:{target_sys_str}",
                icon="LINKED",
            )
            box.label(
                text=f"Target Function: {hook.target.function} {hook.version_constraint}",
                icon="SCRIPT",
            )
            if error:
                error_layout = box.row()
                error_layout.alert = True
                error_layout.label(text=error, icon="ERROR")

    def _draw_system_waiters(self, layout, system: RuntimeSystem):
        if not system.on_ready and not system.on_exit:
            return
        wait_col = layout.column()
        wait_col.label(text="Lifecycle Waiters:", icon="TIME")
        for target in system.on_ready:
            wait_col.label(
                text=f"On Ready -> {target.addon}:{self._format_system_name(target.system)}"
            )
        for target in system.on_exit:
            wait_col.label(
                text=f"On Exit -> {target.addon}:{self._format_system_name(target.system)}"
            )

    def _draw_system(
        self,
        layout,
        addon_path: AddonPath,
        system_name: SystemKey,
        system: RuntimeSystem,
    ):
        system_box = layout.box()
        header_row = system_box.row()
        header_row.label(
            text="Default System"
            if system_name is None
            else f"System: {self._format_system_name(system_name)}",
            icon="PREFERENCES",
        )
        if system.ready:
            header_row_right = header_row.row(align=True)
            header_row_right.alignment = "RIGHT"
            header_row_right.label(text="Marked ready")

        self._draw_system_functions(system_box, addon_path, system_name, system)
        self._draw_system_hooks(system_box, system)
        self._draw_system_waiters(system_box, system)

    def _draw_addon(self, layout, addon_path: AddonPath, addon: RuntimeAddon):
        addon_box = layout.box()
        addon_box.label(
            text=f"Addon: {addon.name} (v{addon.instance_version})", icon="PACKAGE"
        )
        for system_name, system in addon.systems.items():
            self._draw_system(addon_box, addon_path, system_name, system)

    def draw_ui(self, layout):
        """Draws a visual representation of the API Registry inside Blender UI."""
        assert HAS_BPY, "Blender Python API not found"
        addons = self._create_runtime_addons()
        if not addons:
            layout.label(text="No API Addons Registered")
            return

        for addon_path, addon in sorted(
            addons.items(), key=lambda item: (item[1].name, item[0])
        ):
            self._draw_addon(layout, addon_path, addon)


def register_registry(reload: bool = False, with_ui: bool = True):
    """Gets or registers the global API Registry."""
    existing: Optional[ModuleType | APIRegistry] = sys.modules.get(_GLOBAL_KEY)

    if existing is not None and not isinstance(existing, ModuleType):
        if hasattr(existing, "instance_version") and hasattr(existing, "_addons"):
            if MY_VERSION > getattr(existing, "instance_version", 0) or reload:
                logger.info(f"Refreshed API Registry v{MY_VERSION}")
                registry = APIRegistry()
                if getattr(existing, "_registered_ui", False):
                    existing.unregister_bpy_ui_props()
                if with_ui:
                    registry.register_bpy_ui_props()
                registry._addons = getattr(existing, "_addons", {})
                registry._ui_toggles = getattr(existing, "_ui_toggles", {})
                sys.modules[_GLOBAL_KEY] = registry  # type: ignore
                return registry
            return existing  # type: ignore

    logger.info(f"Registering API Registry v{MY_VERSION}")
    registry = APIRegistry()
    if with_ui:
        registry.register_bpy_ui_props()
    sys.modules[_GLOBAL_KEY] = registry  # type: ignore
    return registry


def get_registry():
    """Returns the globally active APIRegistry."""
    return register_registry(with_ui=False)

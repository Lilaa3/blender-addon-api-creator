# Blender Addon API Framework
#### A simplified addon extension api, similar in concept to the glTF 2's extension capabilities but more robust, expendable, versioned and including cross-addon-communication support.
This was written with the intention of using it in [Fast64](https://github.com/Fast-64/Fast64) once robust or in a seperate branch, but it can be used for other addons as well.

> [!WARNING]
> This project is still in early development, it is NOT ready to be used.
> Breaking changes are accepted for now. Even if the registry should be minimally changed from now on.

## Installation

- **The easy way**:

  Copy `blender_api_lib/` into your addon folder.

- **The "right" way** (do this if you intend to publish):
  
  If you intend others to use this, publish it on GitHub or maintain your addon at all, you should use git submodules.

  1. [Install git](https://git-scm.com/install/)
  2. Open a terminal in your addon’s root folder.
  3. Add `blender_api_lib` as a submodule:
     ```bash
     git submodule add https://github.com/Lilaa3/blender_api_lib blender_api_lib
     ```

  4. Initialize and install the submodule:
     ```bash
     git submodule update --init --recursive
     ```
  Then to update to the latest version of the library, run:
  ```bash
  git submodule update --remote
  ```

  Instruct other developers to also update when they clone your addon: 
  ```bash
  git submodule update --init --recursive
  ```

## Guide

### 1. Initialization and Setup
Before using the API features, an addon must register itself with the global registry.
This should be done in your addon's `__init__.py` inside `register()` and `unregister()`.

```python
from .blender_api_lib.registry import register_registry
from .blender_api_lib.client import register_addon, unregister_addon

bl_info = {
    "name": "My Addon",
    "version": (1, 0, 0),
    # ...
}

def register():
    register_registry(reload=True) # Only needed for reloading registry code
    register_addon("MyAddon", bl_info)

def unregister():
    unregister_addon()
```

### 2. Systems
A **System** represents a logical grouping of API functions. Instead of placing every function under a single Addon name, you group them logically, like `("Math", "Core")`

```python
from .blender_api_lib.client import get_or_create_system, register_system, unregister_system

api = get_or_create_system(("Math", "Core"))

def register():
    register_system(api)
    api.finalize_system() # Called once you want on_ready to run.
    # So basically after everything related to the system is done running.

def unregister():
    unregister_system(api)
```

You can also just pass `None` for a un-named system:
```python
api = get_or_create_system(None)
```

### 3. Exposing Functions
To expose a function from your addon so that other addons can hook into it or override it, use the `@api.function` decorator.

```python
from .blender_api_lib.api_types import APIVersion

@api.function("do_math", APIVersion(1, 0, 0))
def do_math(a: int, b: int) -> int:
    print(f"Adding {a} + {b}")
    return a + b
```

Whenever your addon calls `do_math(2, 3)`, the API library intercepts the call, executing any registered hooks (before/after) or overrides from other addons.

### 4. Overriding and Hooking
When replacing or augmenting a function, your decorator must choose one of two signature styles. You cannot mix them.

#### Style A: Standard Arguments
Use this if you only care about the data being passed.
```python
@api.override(target=RuntimeTargetFunction("HostAddon", "do_math", ("Math", "Core")))
def my_custom_math(a: int, b: int):
    return a * b
```

#### Style B: API Context
Use this if you need metadata (who called the function) or need to pass data between hooks. Use `ctx.get_args` to safely retrieve parameters by name regardless of how they were passed.
```python
from .blender_api_lib.api_types import APIContext

@api.override(target=RuntimeTargetFunction("HostAddon", "do_math", ("Math", "Core")))
def my_custom_math(ctx: APIContext):
    a, b = ctx.get_args("a", "b")
    print(f"Call originated from: {ctx.calling_addon}")
    return a * b
```

### 5. Execution Order (Before / After)
Hooks allow code to run without replacing the original logic. 
- **Before**: Runs before the main function. Can modify `ctx.args` or `ctx.kwargs`.
- **After**: Runs after the main function. Can access the result via `ctx.get_data("result")`.

```python
@api.hook(target=RuntimeTargetFunction("HostAddon", "do_math", ("Math", "Core")), when="before")
def log_math(a, b):
    print(f"Processing {a} and {b}")
```

### 6. Inception: Chained Hooks
All types of hooks can be targeted by other addons if they are named. This creates an execution chain where "Addon C" wraps "Addon B" which wraps "Addon A".

```python
@api.override(
    target=RuntimeTargetFunction("HostAddon", "do_math", ("Math", "Core")),
    expose_api_as="complex_math" 
)
def intermediate_step(a, b):
    return (a + b) * 2

# Another addon can now target "complex_math" specifically
@api.hook(target=RuntimeTargetFunction("MyAddon", "complex_math", ("Math", "Core")), when="after")
def cleanup_step(ctx: APIContext):
    print("Complex math finished.")
```

### 7. Yielding and Constraints
To prevent conflicts between multiple addons trying to override the same function, use `yields_to`. If the "better" addon is present, your override will step aside.

```python
@api.override(
    target=RuntimeTargetFunction("HostAddon", "do_math", ("Math", "Core")),
    version=">=1.0",
    requires_provider="OptionalDependency",
    yields_to=[RuntimeTargetFunction("ProMathAddon", "do_math")]
)
def secondary_override(a, b):
    return a + b + 1
```

### 8. Lifecycle Management
Sometimes your addon needs to wait until another addon's system is fully registered and ready before executing setup logic. You can use `@api.on_ready` and `@api.on_exit`.
This can be used, for example, to add properties to PropertyGroups.
These will still run if the consumer is registered after or before the host, meaning there is no worry over addon instalation order like typical methods!

```python
from .blender_api_lib.api_types import RuntimeTargetAddon

@api.on_ready(RuntimeTargetAddon("HostAddon", ("Math", "Core")))
def on_host_ready():
    print("Host addon is loaded! We can now safely do things.")

@api.on_exit(RuntimeTargetAddon("HostAddon", ("Math", "Core")))
def on_host_exit():
    print("Host addon was unregistered. Clean up our resources.")
```

### 9. Module Access
If you need to access variables or classes directly from a host addon, the host must first expose its module.

**Host:**
```python
import sys
api.expose_module(sys.modules[__name__])
```

**Consumer:**
```python
from .blender_api_lib.client import get_system_module
host_mod = get_system_module("HostAddon", system_name=("Math", "Core"))
if host_mod:
    print(host_mod.SOME_CONSTANT)
```

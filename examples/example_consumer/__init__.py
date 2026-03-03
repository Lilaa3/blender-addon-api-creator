from .blender_api_lib.api_types import (
    APIContext,
    RuntimeTargetFunction,
    RuntimeTargetAddon,
    RuntimeExposedHook,
    APIVersion,
)

from .blender_api_lib.client import (
    get_system_module,
    get_or_create_system,
    register_addon,
    register_system,
    unregister_addon,
    unregister_system,
)

bl_info = {
    "name": "Consumer API Addon",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 2, 0),
    "description": "Example Consumer Addon using an API",
    "category": "Development",
}

api = get_or_create_system(None)


print("Registering Consumer Addon and overriding Host's do_math function.")


@api.override(
    target=RuntimeTargetFunction("HostAddon", "do_math", ("Math", "Core")),
    yields_to=[RuntimeTargetFunction("SpecialAddon", "do_divide")],
    expose_api_as=RuntimeExposedHook("do_multiply"),
)
def do_multiply(ctx: APIContext) -> int:
    """Overrides the Host's do_math to perform multiplication instead of addition."""
    print(ctx)
    a, b = ctx.args
    print(f"[Consumer] Performing math: {a} * {b}")
    return a * b


@api.hook(
    target=RuntimeTargetFunction("HostAddon", "API_OT_DoMath.draw", ("Math", "Core")),
    when="before",
    expose_api_as=RuntimeExposedHook("draw_consumer_text", APIVersion(1, 0, 0)),
)
def draw_operator_ui(self, context):
    self.layout.label(text="[Consumer] IT'S MULTIPLY TIME!")


@api.on_ready(RuntimeTargetAddon("HostAddon", ("Math", "Core")))
def host_addon_post_register():
    print("[Consumer] Host Addon is ready!")

    host = get_system_module("HostAddon", system_name=("Math", "Core"))
    if host is not None:
        print(f"[Consumer] Host module: {host}")
        print(f"[Consumer] Host bl_info: {host.bl_info}")

        host.utils.thing()


@api.on_exit(RuntimeTargetAddon("HostAddon", ("Math", "Core")))
def host_addon_post_unregister():
    print("[Consumer] Host Addon has been unregistered!")


def register():
    register_addon("ConsumerAddon", {"bl_info": bl_info})
    register_system(api)

    api.finalize_system()


def unregister():
    unregister_system(api)
    unregister_addon()

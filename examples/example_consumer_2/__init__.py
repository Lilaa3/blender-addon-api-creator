from .blender_api_lib.types import APIContext, RuntimeTargetFunction

from .blender_api_lib.client import (
    get_or_create_system,
    register_addon,
    register_system,
    unregister_addon,
    unregister_system,
)

bl_info = {
    "name": "Consumer 2 API Addon",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 2, 0),
    "description": "Example Consumer 2 Addon using an API",
    "category": "Development",
}

api = get_or_create_system(None)


@api.hook(target=RuntimeTargetFunction("ConsumerAddon", "do_multiply"))
def hi(ctx: APIContext) -> int:
    print("Hi, I target a specific override")


@api.hook(
    target=RuntimeTargetFunction("HostAddon", "do_math", ("Math", "Core")),
    when="before",
)
def hi_old(a: int, b: int) -> int:
    print("Hi, I target the original function")


@api.hook(
    target=RuntimeTargetFunction(
        "HostAddon", "unstable.API_OT_DoMath.execute", ("Math", "Core")
    ),
    when="before",
)
def before_execute(a: int, b: int) -> int:
    print("Hi, I target an unstable function")


@api.hook(
    target=RuntimeTargetFunction("ConsumerAddon", "draw_consumer_text"),
    when="after",
)
def hook_into_hook(ctx: APIContext):
    print("Draw was done in consumer")


def register():
    register_addon("ConsumerAddon2", {"bl_info": bl_info})
    register_system(api)

    api.finalize_system()


def unregister():
    unregister_system(api)
    unregister_addon()

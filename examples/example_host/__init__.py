import bpy
import sys
from . import utils

from .blender_api_lib.registry import register_registry
from .blender_api_lib.api_types import APIVersion
from .blender_api_lib.client import (
    get_or_create_system,
    register_addon,
    register_system,
    unregister_addon,
    unregister_system,
    get_registry,
)

bl_info = {
    "name": "Host Addon",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 2, 0),
    "description": "Example Host Addon defining an API",
    "category": "Development",
}

api = get_or_create_system(("Math", "Core"))


@api.function("do_math", APIVersion(1, 0, 0))
def do_math(a: int, b: int):
    print(f"[Host] Performing math: {a} + {b}")
    return a + b


class API_OT_DoMath(bpy.types.Operator):
    bl_idname = "api.do_math"
    bl_label = "Do Math"

    a: bpy.props.IntProperty(name="A", default=3)
    b: bpy.props.IntProperty(name="B", default=2)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    @api.function("API_OT_DoMath.draw")
    def draw(self, context):
        self.layout.label(text="Hi!")
        self.layout.prop(self, "a")
        self.layout.prop(self, "b")

    def execute(self, context):
        result = do_math(self.a, self.b)
        self.report({"INFO"}, f"Result: {result}")
        return {"FINISHED"}


class API_PT_HostActions(bpy.types.Panel):
    bl_label = "Host Actions"
    bl_idname = "API_PT_HostActions"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "API Manager"

    def draw(self, context):
        self.layout.operator("api.do_math", text="Perform Math")
        get_registry().draw_ui(self.layout)


classes = (API_OT_DoMath, API_PT_HostActions)

api.expose_module(sys.modules[__name__])

# Automatically expose all un-wrapped functions in the `utils` module,
# except for the one specifically excluded.
api.expose_all(
    sys.modules[__name__],
    exclude=["unstable.blender_api_lib*", "unstable.utils.exclude_me"],
    starting_prefix="unstable.",
)


def register():
    register_registry(
        reload=True, with_ui=True
    )  # techinically not needed if you don't want reload
    register_addon(name="HostAddon", bl_info=bl_info)
    register_system(api)

    for cls in classes:
        bpy.utils.register_class(cls)

    api.finalize_system()


def unregister():
    unregister_addon()
    unregister_system(api)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

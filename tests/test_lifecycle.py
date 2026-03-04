from blender_api_lib.api_types import RuntimeTargetAddon
from conftest import create_system, create_addon, core_target_addon, reg
from blender_api_lib import client


class TestLifecycle:
    def test_ready_and_exit_order(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",))
        b, s_b = create_system("Addon B", {}, "addon_b", None)
        ready = exit = False

        @s_b.on_ready(core_target_addon())
        def on_ready():
            nonlocal ready
            ready = True

        @s_b.on_exit(core_target_addon())
        def on_exit():
            nonlocal exit
            exit = True

        b.register_system(s_b)
        a.register_system(s_a)

        assert not ready
        assert not exit
        s_a.finalize_system()

        assert ready
        assert not exit
        ready = exit = False

        a.unregister_system(s_a.system_name)

        assert not ready
        assert exit
        ready = exit = False

        a, s_a = create_system("Addon A", {}, "addon_a", ("core",), True)
        a.unregister_addon()

        assert not ready
        assert exit

    def test_ready_fires_immediately_if_finalized(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",), True)
        s_a.finalize_system()

        b, s_b = create_system("Addon B", {}, "addon_b", None)
        fired = False

        @s_b.on_ready(core_target_addon())
        def on_ready():
            nonlocal fired
            fired = True

        assert not fired
        b.register_system(s_b)
        assert fired

    def test_double_finalize_idempotent(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",), True)
        b, s_b = create_system("Addon B", {}, "addon_b", None)
        fired = []

        @s_b.on_ready(core_target_addon())
        def on_ready():
            fired.append(True)

        b.register_system(s_b)
        s_a.finalize_system()
        s_a.finalize_system()

        assert len(fired) == 1

    def test_multiple_listeners_all_fire(self):
        a, s_a = create_system("Addon A", {}, "addon_a", ("core",), True)
        b, s_b = create_system("Addon B", {}, "addon_b", None)
        c, s_c = create_system("Addon C", {}, "addon_c", None)
        b_fired = c_fired = False

        @s_b.on_ready(core_target_addon())
        def b_ready():
            nonlocal b_fired
            b_fired = True

        @s_c.on_ready(core_target_addon())
        def c_ready():
            nonlocal c_fired
            c_fired = True

        b.register_system(s_b)
        c.register_system(s_c)

        assert not b_fired
        assert not c_fired

        s_a.finalize_system()

        assert b_fired
        assert c_fired

    def test_exit_fires_for_all_systems_on_unregister(self):
        a = create_addon("Addon A", {}, "addon_a")
        s1 = client.APISystem(system_name=("s1",), _addon_path="addon_a")
        s2 = client.APISystem(system_name=("s2",), _addon_path="addon_a")
        a.register_system(s1)
        a.register_system(s2)

        b, s_b = create_system("Addon B", {}, "addon_b", None)
        exits = []

        @s_b.on_exit(RuntimeTargetAddon("Addon A", ("s1",)))
        def on_s1_exit():
            exits.append("s1")

        @s_b.on_exit(RuntimeTargetAddon("Addon A", ("s2",)))
        def on_s2_exit():
            exits.append("s2")

        b.register_system(s_b)
        a.unregister_addon()

        assert "s1" in exits
        assert "s2" in exits

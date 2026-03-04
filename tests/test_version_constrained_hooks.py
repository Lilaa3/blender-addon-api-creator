from conftest import reg, V, target


class TestVersionConstrainedHooks:
    def test_version_satisfied(self, two_addons):
        (addon_a, sys_a), (addon_b, sys_b) = two_addons
        called = []

        @sys_a.function(name="versioned", version=V(2, 0, 0))
        def versioned():
            return "main"

        @sys_b.hook(target("versioned"), when="before", version_constraint=">=2.0.0")
        def before_versioned():
            called.append(True)

        reg((addon_a, sys_a), (addon_b, sys_b))
        versioned()
        assert called == [True], "Hook should run when version constraint is satisfied"

    def test_version_not_satisfied(self, two_addons):
        (addon_a, sys_a), (addon_b, sys_b) = two_addons
        called = []

        @sys_a.function(name="versioned", version=V(1, 0, 0))
        def versioned():
            return "main"

        @sys_b.hook(target("versioned"), when="before", version_constraint=">=2.0.0")
        def before_versioned():
            called.append(True)

        reg((addon_a, sys_a), (addon_b, sys_b))
        versioned()
        assert called == [], "Hook must not run when version constraint is not met"

    def test_no_version(self, two_addons):
        (addon_a, sys_a), (addon_b, sys_b) = two_addons
        called = []

        @sys_a.function(name="versionless")
        def versionless():
            return "main"

        @sys_b.hook(target("versionless"), when="before", version_constraint=">=2.0.0")
        def before_versionless():
            called.append(True)

        reg((addon_a, sys_a), (addon_b, sys_b))
        versionless()
        assert called == [], "Hook must not run when version constraint is not met"

    def test_no_constraint(self, two_addons):
        (addon_a, sys_a), (addon_b, sys_b) = two_addons
        called = []

        @sys_a.function(name="versioned", version=V(2, 0, 0))
        def versioned():
            return "main"

        @sys_b.hook(target("versioned"), when="before")
        def before_versioned():
            called.append(True)

        reg((addon_a, sys_a), (addon_b, sys_b))
        versioned()
        assert called, "Hook should run when no version constraint is specified"

import pytest

from blender_api_lib.api_types import APIVersion


class TestAPIVersion:
    def test_empty_constraint_always_matches(self):
        assert APIVersion(1, 2, 3).match(""), "Empty constraint should always match"

    @pytest.mark.parametrize(
        "constraint,matches",
        [
            ("==2", True),
            ("==3", False),
        ],
    )
    def test_exact_match_major_only(self, constraint, matches):
        assert APIVersion(2, 0, 0).match(constraint) == matches

    @pytest.mark.parametrize(
        "constraint,matches",
        [
            ("==1.2.3", True),
            ("==1.2.4", False),
        ],
    )
    def test_exact_match_full(self, constraint, matches):
        assert APIVersion(1, 2, 3).match(constraint) == matches

    @pytest.mark.parametrize(
        "major,minor,patch,constraint,matches",
        [
            (2, 0, 0, ">=2.0.0", True),
            (2, 0, 1, ">=2.0.0", True),
            (1, 9, 9, ">=2.0.0", False),
            (1, 0, 0, "<=1.0.0", True),
            (0, 9, 9, "<=1.0.0", True),
            (1, 0, 1, "<=1.0.0", False),
            (2, 0, 1, ">2.0.0", True),
            (2, 0, 0, ">2.0.0", False),
            (1, 9, 9, "<2.0.0", True),
            (2, 0, 0, "<2.0.0", False),
        ],
    )
    def test_comparison_operators(self, major, minor, patch, constraint, matches):
        assert APIVersion(major, minor, patch).match(constraint) == matches

    def test_none_version_never_matches_nonempty_constraint(self):
        v = APIVersion()
        assert v.is_none
        assert not v.match(">=1.0.0"), "None version should not satisfy a constraint"
        assert not v.match("==1.0"), "None version should not satisfy ==1.0"

    def test_invalid_constraint_raises(self):
        with pytest.raises(ValueError):
            APIVersion(1, 0, 0).match("~=1.0")

    def test_str_none_version(self):
        assert str(APIVersion()) == "None"

    def test_str_versioned(self):
        assert str(APIVersion(1, 2, 3)) == "1.2.3"

    def test_from_tuple_roundtrip(self):
        t = (3, 7, 1)
        assert APIVersion.from_tuple(t).to_tuple() == t

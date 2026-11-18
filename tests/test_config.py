import pytest

from fastmap.core.config import parse_render_limits


def test_defaults():
    assert parse_render_limits({}) == (2, 10, 1800.0)


def test_values_from_environment():
    env = {"RENDER_WORKERS": "3", "MAX_PENDING_JOBS": "6", "JOB_TTL_S": "90.5"}
    assert parse_render_limits(env) == (3, 6, 90.5)


@pytest.mark.parametrize(
    ("env", "name"),
    [
        ({"RENDER_WORKERS": "0"}, "RENDER_WORKERS"),
        ({"RENDER_WORKERS": "two"}, "RENDER_WORKERS"),
        ({"MAX_PENDING_JOBS": "0"}, "MAX_PENDING_JOBS"),
        ({"RENDER_WORKERS": "4", "MAX_PENDING_JOBS": "3"}, "MAX_PENDING_JOBS"),
        ({"JOB_TTL_S": "0"}, "JOB_TTL_S"),
        ({"JOB_TTL_S": "-5"}, "JOB_TTL_S"),
        ({"JOB_TTL_S": "1800   # seconds"}, "JOB_TTL_S"),  # inline comment via --env-file
    ],
)
def test_bad_values_name_the_variable(env, name):
    with pytest.raises(ValueError, match=name):
        parse_render_limits(env)


def test_env_example_has_no_inline_comments_on_settings():
    """`docker run --env-file` keeps '# ...' as part of the value."""
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    for line in example.read_text().splitlines():
        setting = line.lstrip("#").strip()
        if "=" in setting and setting.split("=", 1)[0].isupper():
            assert "#" not in setting.split("=", 1)[1], line

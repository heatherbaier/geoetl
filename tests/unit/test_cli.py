from geoetl.cli import _expand_env_vars


def test_plain_string_passes_through_unchanged():
    assert _expand_env_vars("plain value") == "plain value"


def test_substitutes_a_set_env_var(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "secret123")
    assert _expand_env_vars("key=${MY_API_KEY}") == "key=secret123"


def test_unset_env_var_expands_to_empty_string(monkeypatch):
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
    assert _expand_env_vars("${DEFINITELY_NOT_SET}") == ""


def test_recurses_into_nested_dicts_and_lists(monkeypatch):
    monkeypatch.setenv("REGION", "us-west")
    value = {
        "auth": {"token": "${REGION}-token"},
        "regions": ["${REGION}", "static"],
    }
    assert _expand_env_vars(value) == {
        "auth": {"token": "us-west-token"},
        "regions": ["us-west", "static"],
    }


def test_non_string_scalars_pass_through_unchanged():
    assert _expand_env_vars(42) == 42
    assert _expand_env_vars(True) is True
    assert _expand_env_vars(None) is None

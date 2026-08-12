"""Security tests for secret masking (roadmap Phase 3: secrets never leak)."""
from app.core.secrets import SecretStore


def test_masks_registered_value():
    s = SecretStore()
    s.set("API_KEY", "sk-ant-super-secret-value-123456")
    out = s.mask("using sk-ant-super-secret-value-123456 to call the model")
    assert "sk-ant-super-secret-value-123456" not in out
    assert "••••••••" in out


def test_masks_longest_first():
    s = SecretStore()
    s.set("SHORT", "abcdef")
    s.set("LONG", "abcdef-ghijkl-mnopqr")
    out = s.mask("value abcdef-ghijkl-mnopqr here")
    assert "abcdef-ghijkl-mnopqr" not in out


def test_no_secrets_is_passthrough():
    s = SecretStore()
    assert s.mask("nothing to hide") == "nothing to hide"


def test_short_values_not_masked():
    # values under 6 chars are too collision-prone to mask safely
    s = SecretStore()
    s.set("PIN", "abc")
    assert s.mask("abc def") == "abc def"

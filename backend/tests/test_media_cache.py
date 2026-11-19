from app.services.media_cache import cache_key

BASE = dict(model="m", prompt="p", seed=1, input_sha256="abc", settings={"aspect_ratio": "9:16"})


def test_same_inputs_same_key_and_settings_order_does_not_matter():
    a = cache_key(**BASE)
    b = cache_key(**{**BASE, "settings": {"aspect_ratio": "9:16"}})
    assert a == b and len(a) == 64
    assert cache_key(**{**BASE, "settings": {"x": 1, "y": 2}}) == cache_key(**{**BASE, "settings": {"y": 2, "x": 1}})


def test_every_component_changes_the_key():
    base = cache_key(**BASE)
    for field, value in [
        ("model", "m2"),
        ("prompt", "p2"),
        ("seed", 2),
        ("input_sha256", "abd"),
        ("settings", {"aspect_ratio": "1:1"}),
    ]:
        assert cache_key(**{**BASE, field: value}) != base, field

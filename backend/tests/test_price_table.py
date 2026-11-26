"""Guardrail (M1): the cost estimate is correct for every billing unit in the price table."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services import llm_trace as lt
from app.services.llm_trace import Price, Usage, cost_usd, money, normalise_unit, price_for, usd_to_eur
from app.services.pipeline import estimate_job_usd


def test_per_image():
    assert cost_usd("fal-ai/nano-banana/edit", Usage(images=1)) == pytest.approx(0.0398)
    assert cost_usd("fal-ai/nano-banana/edit", Usage(images=3)) == pytest.approx(0.1194)


def test_per_second_video():
    model = "fal-ai/kling-video/v2.5-turbo/pro/image-to-video"
    assert cost_usd(model, Usage(seconds=5)) == pytest.approx(0.35)
    assert cost_usd(model, Usage(seconds=10)) == pytest.approx(0.70)


def test_per_megapixel():
    p = Price(unit="megapixel", usd=0.025)
    assert cost_usd("x", Usage(megapixels=2.1), p) == pytest.approx(0.0525)


def test_per_video():
    p = Price(unit="video", usd=0.4)
    assert cost_usd("x", Usage(videos=2), p) == pytest.approx(0.8)


def test_per_generic_unit():
    p = Price(unit="unit", usd=0.002)
    assert cost_usd("x", Usage(units=150), p) == pytest.approx(0.3)


def test_per_token_with_cached_input():
    # gpt-5-mini: 0.25 in, 0.025 cached, 2.00 out per 1M tokens
    u = Usage(input_tokens=10_000, cached_input_tokens=4_000, output_tokens=2_000)
    expected = 6_000 / 1e6 * 0.25 + 4_000 / 1e6 * 0.025 + 2_000 / 1e6 * 2.00
    assert cost_usd("gpt-5-mini-2025-08-07", u) == pytest.approx(expected)


def test_token_cached_defaults_to_input_rate_and_never_exceeds_input():
    p = Price(unit="token", input_per_m=1.0, output_per_m=2.0)
    assert cost_usd("x", Usage(input_tokens=1_000_000, cached_input_tokens=5_000_000), p) == pytest.approx(1.0)


def test_per_character():
    assert cost_usd("tts-1", Usage(characters=2_000)) == pytest.approx(0.03)


def test_tts_tokens():
    assert cost_usd("gpt-4o-mini-tts", Usage(input_tokens=1_000, output_tokens=10_000)) == pytest.approx(
        1_000 / 1e6 * 0.60 + 10_000 / 1e6 * 12.0
    )


def test_base_fee_plus_per_second():
    p = Price(unit="second", usd=0.05, base_usd=0.10)
    assert cost_usd("x", Usage(seconds=4), p) == pytest.approx(0.30)


def test_audio_on_off():
    p = Price(unit="second", usd=0.10, audio_on_multiplier=1.5)
    assert cost_usd("x", Usage(seconds=5), p) == pytest.approx(0.50)
    assert cost_usd("x", Usage(seconds=5, audio=True), p) == pytest.approx(0.75)


def test_resolution_multiplier_and_unknown_resolution():
    p = Price(unit="second", usd=0.10, resolution_multipliers=(("720p", 1.0), ("1080p", 2.0)))
    assert cost_usd("x", Usage(seconds=5, resolution="1080p"), p) == pytest.approx(1.0)
    with pytest.raises(lt.UnknownPrice):
        cost_usd("x", Usage(seconds=5, resolution="4k"), p)


def test_unknown_model_is_refused_not_priced_zero():
    with pytest.raises(lt.UnknownPrice):
        cost_usd("some/unpriced-model", Usage(images=1))


def test_longest_prefix_wins():
    assert price_for("gpt-5-mini-2025-08-07").output_per_m == 2.00
    assert price_for("gpt-5-nano-2025-08-07").output_per_m == 0.40


def test_fal_plural_units_normalise():
    assert normalise_unit("images") == "image"
    assert normalise_unit("seconds") == "second"
    with pytest.raises(ValueError):
        normalise_unit("frames")


def test_every_priced_model_has_a_known_unit_and_source():
    for model, p in lt.PRICES.items():
        assert normalise_unit(p.unit) == p.unit, model
        assert p.source and p.checked, model


def test_eur_conversion_and_usd_display():
    assert usd_to_eur(1.0, 0.87) == 0.87
    assert money(0.35, 0.87) == {"usd": 0.35, "eur": 0.3045}


def test_job_estimate_matches_table_and_fits_the_cap():
    """M2: three scenes, each one reference image, one 5 s clip and one voiceover line (D2, D26)."""
    s = Settings(_env_file=None)
    assert s.render_scenes == 20  # at most 20 shots (D32); an ad without a story has 3 (D28)
    media = 3 * (0.0398 + 0.35)
    voice = estimate_job_usd(s) - media
    assert 0 < voice < 0.01  # three voiceover lines cost well under a cent together
    assert estimate_job_usd(s) * s.usd_to_eur_rate < s.job_cost_cap_eur

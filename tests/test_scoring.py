from datetime import UTC, datetime, timedelta

import pytest

from tension_index.scoring import Signal, advisory_strength, compute_score, load_config

NOW = datetime(2026, 9, 30, tzinfo=UTC)
CFG = load_config()


def adv(country="MD", publisher="us", level="4", reason="armed_conflict", **kw) -> Signal:
    return Signal(
        country=country,
        block="advisories",
        kind="advisory_level",
        strength=advisory_strength(CFG, publisher, level),
        publisher=publisher,
        observed_at=kw.pop("observed_at", NOW - timedelta(days=60)),
        reason=reason,
        state=True,
        **kw,
    )


def staff(publisher, posture, country="PL") -> Signal:
    return Signal(
        country=country,
        block="advisories",
        kind=f"staff_posture:{posture}",
        strength=CFG["staff_posture"][posture],
        publisher=publisher,
        observed_at=NOW - timedelta(days=1),
        reason="armed_conflict",
        state=True,
    )


def test_no_signals_is_green():
    result = compute_score("PL", [], NOW)
    assert result.score == 0.0 and result.level == "green"


def test_reason_matters():
    war = compute_score("MD", [adv(reason="armed_conflict")], NOW).score
    terror = compute_score("MD", [adv(reason="terrorism")], NOW).score
    assert war > terror > 0


def test_same_publisher_does_not_stack_but_independent_ones_do():
    one = compute_score("MD", [adv()], NOW).blocks["advisories"]
    repeated = compute_score("MD", [adv(), adv()], NOW).blocks["advisories"]
    two = compute_score("MD", [adv(), adv(publisher="au")], NOW).blocks["advisories"]
    assert one == pytest.approx(repeated)
    assert two > one


def test_nato_eu_advisories_weigh_less():
    md = compute_score("MD", [adv(country="MD")], NOW).raw
    pl = compute_score("PL", [adv(country="PL")], NOW).raw
    assert md > pl


def test_events_decay_with_half_life():
    fresh = Signal("PL", "aggressor", "rhetoric", 0.8, "ru_mfa", NOW, reason="military_threat")
    old = Signal(
        "PL",
        "aggressor",
        "rhetoric",
        0.8,
        "ru_mfa",
        NOW - timedelta(days=14),
        reason="military_threat",
    )
    b_fresh = compute_score("PL", [fresh], NOW).blocks["aggressor"]
    b_old = compute_score("PL", [old], NOW).blocks["aggressor"]
    assert b_old == pytest.approx(b_fresh / 2)


def test_floors():
    one = compute_score("PL", [staff("us", "authorized_departure")], NOW)
    assert one.score >= 7.0 and one.level == "red"
    single_ordered = compute_score("PL", [staff("us", "ordered_departure")], NOW)
    assert 7.0 <= single_ordered.score < 9.0
    two = compute_score(
        "PL", [staff("us", "ordered_departure"), staff("gov_uk", "ordered_departure")], NOW
    )
    assert two.score >= 9.0 and two.level == "critical"
    closed = Signal("EE", "aviation", "aviation:airspace_closed", 1.0, "easa", NOW, state=True)
    assert compute_score("EE", [closed], NOW).score < 8.0  # one publisher: no floor
    also = Signal("EE", "aviation", "aviation:airspace_closed", 1.0, "gov_uk", NOW, state=True)
    assert compute_score("EE", [closed, also], NOW).score >= 8.0


def test_unconfirmed_low_tier_is_ignored():
    rumour = Signal("LT", "media", "osint", 1.0, "tg_channel", NOW, tier=4)
    result = compute_score("LT", [rumour], NOW)
    assert result.score == 0.0 and result.dropped_unverified == 1
    rumour.confirmed = True
    assert compute_score("LT", [rumour], NOW).score > 0


def raised(publisher, reason="armed_conflict", kind="advisory_update:level_raised", days=2):
    return Signal(
        country="MD", block="advisories", kind=kind, strength=0.4, publisher=publisher,
        observed_at=NOW - timedelta(days=days), reason=reason,
    )  # fmt: skip


def test_synchrony_flag():
    signals = [adv(publisher=p, level="3") for p in ("us", "au", "gov_uk")]
    signals += [raised(p) for p in ("us", "au", "gov_uk")]
    result = compute_score("MD", signals, NOW)
    assert "synchrony:3" in result.flags


def test_synchrony_ignores_standing_levels_rewording_and_terrorism():
    """Levels seen recently, routine updates and terrorism notes are not governments
    tightening together (France, November 2015, was a false alarm before this rule)."""
    signals = [
        adv(publisher=p, level="3", observed_at=NOW - timedelta(days=1))
        for p in ("us", "au", "gov_uk")
    ]
    signals += [raised(p, kind="advisory_update:security_update") for p in ("us", "au")]
    signals += [raised("gov_uk", reason="terrorism"), raised("ca", reason="terrorism")]
    assert not any(f.startswith("synchrony") for f in compute_score("MD", signals, NOW).flags)


def test_surge_bonus_is_capped():
    """One government's ordered departure in a calm country stays at its floor (7), the
    surge over a flat norm must not lift it to 9+."""
    signals = [staff("us", "ordered_departure")]
    result = compute_score("PL", signals, NOW, history=[0.0] * 180, history_days=180)
    assert 7.0 <= result.score < 8.0


def test_surge_above_own_norm_and_isolation():
    signals = [adv(level="3")]
    flat = compute_score("MD", signals, NOW, history=[0.0] * 90, history_days=90)
    assert "short_history" not in flat.flags
    assert flat.score > compute_score("MD", signals, NOW).score  # surge bonus
    isolated = compute_score(
        "MD", signals, NOW, history=[0.0] * 90, history_days=90, peers_surging=[False, False]
    )
    assert "isolated" in isolated.flags
    regional = compute_score(
        "MD", signals, NOW, history=[0.0] * 90, history_days=90, peers_surging=[True, True, False]
    )
    assert "regional_escalation" in regional.flags


def test_low_coverage_withholds_score():
    result = compute_score("PL", [], NOW, covered_blocks={"markets"})
    assert result.score is None and "low_coverage" in result.flags


def test_measures_for_covid_do_not_trigger_floors():
    """Armenia/Azerbaijan, June 2020: COVID flight bans and reduced consular services."""
    covid = staff("us", "authorized_departure")
    covid.reason = "health"
    assert compute_score("PL", [covid], NOW).score < 7.0

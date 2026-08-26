import pandas as pd

from datapulse.core.quality import CLEAN, Between, Ordered, PeerRatio, apply_rules


def _prices(values, commodity="Potato"):
    return pd.DataFrame({"commodity": commodity, "modal_price": values})


def test_clean_rows_get_an_empty_flag():
    df = _prices([2000, 2100, 1900, 2050, 2200])
    flags = apply_rules(df, (PeerRatio("modal_price", ["commodity"]),))
    assert (flags == CLEAN).all()


def test_peer_ratio_catches_a_per_kilogram_price_in_a_per_quintal_column():
    """The real case: one market reports 0.20 against a median near 2000."""
    df = _prices([2000, 2100, 1900, 2050, 2200, 0.20])
    flags = apply_rules(df, (PeerRatio("modal_price", ["commodity"], factor=20),))
    assert flags.iloc[-1] == "peer_outlier"
    assert (flags.iloc[:-1] == CLEAN).all()


def test_peer_ratio_leaves_genuine_regional_spread_alone():
    """Potatoes vary a lot between states -- that is signal, not an error."""
    df = _prices([2200, 2900, 1800, 3400, 2600])
    flags = apply_rules(df, (PeerRatio("modal_price", ["commodity"], factor=20),))
    assert (flags == CLEAN).all()


def test_peer_ratio_compares_within_a_commodity_not_across():
    """Cardamom at 272,500 is not an outlier -- it is expensive."""
    df = pd.DataFrame(
        {
            "commodity": ["Cardamom"] * 5 + ["Potato"] * 5,
            "modal_price": [272500, 270000, 275000, 268000, 271000, 2000, 2100, 1900, 2050, 2200],
        }
    )
    flags = apply_rules(df, (PeerRatio("modal_price", ["commodity"], factor=20),))
    assert (flags == CLEAN).all()


def test_small_groups_are_skipped():
    """A median over two rows is not a baseline worth trusting."""
    df = _prices([2000, 0.20])
    flags = apply_rules(df, (PeerRatio("modal_price", ["commodity"], min_group=5),))
    assert (flags == CLEAN).all()


def test_ordered_catches_modal_outside_min_max():
    df = pd.DataFrame(
        {"min_price": [100, 100], "modal_price": [150, 90], "max_price": [200, 200]}
    )
    flags = apply_rules(df, (Ordered(["min_price", "modal_price", "max_price"]),))
    assert flags.tolist() == [CLEAN, "order_invalid"]


def test_between_flags_absolute_bounds_and_ignores_nulls():
    df = pd.DataFrame({"modal_price": [50, 5, None]})
    flags = apply_rules(df, (Between("modal_price", low=10),))
    assert flags.tolist() == [CLEAN, "out_of_range", CLEAN]


def test_multiple_failures_are_listed_together():
    df = pd.DataFrame(
        {
            "commodity": ["Potato"] * 6,
            "min_price": [100] * 6,
            "modal_price": [2000, 2100, 1900, 2050, 2200, 0.20],
            "max_price": [3000] * 6,
        }
    )
    rules = (
        Ordered(["min_price", "modal_price", "max_price"]),
        PeerRatio("modal_price", ["commodity"], factor=20),
    )
    flags = apply_rules(df, rules)
    # 0.20 is both below min_price and far off its peers.
    assert flags.iloc[-1] == "order_invalid,peer_outlier"


def test_rules_tolerate_a_missing_column():
    """A source may not carry every column; a rule must not crash the run."""
    df = pd.DataFrame({"other": [1, 2, 3]})
    flags = apply_rules(df, (PeerRatio("modal_price", ["commodity"]), Between("nope", low=0)))
    assert (flags == CLEAN).all()


def test_empty_frame_returns_empty_flags():
    assert apply_rules(pd.DataFrame(), (Between("x", low=0),)).empty

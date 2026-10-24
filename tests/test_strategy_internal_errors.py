"""验证策略内部真实计算异常向上传播，避免误记未命中或绕过必要阶段。"""

import pandas as pd
import pytest

from strategy.b1_case_analyzer import B1CaseStrategy
from strategy.b2_strategy import B2Strategy
from strategy.zettaranc_combo import MIN_HISTORY, ZettarancComboStrategy


def _b1_prepared_frame():
    frame = pd.DataFrame({
        'date': pd.bdate_range('2026-01-01', periods=80),
        'open': 10.0,
        'close': 10.0,
        'low': 10.0,
        'K': 50.0,
        'D': 50.0,
        'J': 50.0,
        'short_term_trend': 11.0,
        'bull_bear_line': 10.0,
        'distance_to_bullbear_pct': 0.0,
    })
    # 第 20 根为锚点，随后守价、连续三阳，最后两根进入 setup 窗口。
    frame.loc[20, 'J'] = 10.0
    frame.loc[24:26, 'close'] = [10.5, 11.0, 11.5]
    frame.loc[78:79, 'J'] = 10.0
    return frame


def test_b1_valid_pre_signal_preserves_all_five_stages():
    result = B1CaseStrategy().scan_pre_signal(_b1_prepared_frame())
    assert result['detected'] is True
    assert result['stage_passed'] == {1: True, 2: True, 3: True, 4: True, 5: True}
    assert result['anchor_j'] == 10.0
    assert result['support_price'] == 10.0
    assert result['current_j'] == 10.0


@pytest.mark.parametrize(('row', 'column'), [
    pytest.param(79, 'J', id='current-indicator'),
    pytest.param(54, 'J', id='anchor-indicator'),
    pytest.param(20, 'open', id='anchor-open'),
    pytest.param(22, 'low', id='guard-low'),
    pytest.param(24, 'open', id='breakout-open'),
    pytest.param(18, 'low', id='support-low-must-not-pass-stage-four'),
    pytest.param(40, 'close', id='washout-close'),
    pytest.param(78, 'J', id='setup-indicator'),
    pytest.param(78, 'distance_to_bullbear_pct', id='setup-distance'),
])
def test_b1_invalid_stage_data_raises_instead_of_no_match_or_pass(row, column):
    frame = _b1_prepared_frame()
    frame[column] = frame[column].astype(object)
    frame.loc[row, column] = 'broken-number'
    with pytest.raises((TypeError, ValueError)):
        B1CaseStrategy().select_stocks(frame, '测试股份')


def test_b1_normal_empty_nan_and_failed_threshold_still_have_no_signal():
    strategy = B1CaseStrategy()
    assert strategy.select_stocks(pd.DataFrame()) == []
    frame = _b1_prepared_frame()
    frame['J'] = float('nan')
    assert strategy.select_stocks(frame, '测试股份') == []
    frame = _b1_prepared_frame()
    frame.loc[22, 'low'] = 9.0
    assert strategy.select_stocks(frame, '测试股份') == []


def _consolidation_frame():
    return pd.DataFrame({
        'date': pd.to_datetime(['2026-10-19', '2026-10-20', '2026-10-21']),
        'high': [10.0, 12.0, 11.0],
        'close': [9.0, 11.0, 10.0],
        'low': [8.0, 9.0, 9.0],
    })


def test_b2_invalid_consolidation_date_is_an_error():
    analyzer = B2Strategy().library.analyzer
    with pytest.raises(ValueError):
        analyzer._identify_consolidation(_consolidation_frame(), 'invalid-date', '2026-10-21')


def test_b2_consolidation_missing_price_column_is_an_error():
    analyzer = B2Strategy().library.analyzer
    with pytest.raises(KeyError, match='high'):
        analyzer._identify_consolidation(
            _consolidation_frame().drop(columns='high'), '2026-10-19', '2026-10-21')


def test_b2_valid_and_empty_consolidation_windows_keep_existing_results():
    analyzer = B2Strategy().library.analyzer
    assert analyzer._identify_consolidation(
        _consolidation_frame(), '2026-10-19', '2026-10-21') == {
            'high': 12.0, 'breakout_level': 11.0, 'low': 8.0,
            'start': '2026-10-19', 'end': '2026-10-21',
        }
    assert analyzer._identify_consolidation(
        _consolidation_frame(), '2026-10-01', '2026-10-02') is None


def _zettaranc_ready_row():
    return {
        'short_term_trend': 11.0, 'bull_bear_line': 10.0,
        'J': -5.0, 'j_prev': -10.0, 'bbi': 10.0, 'vol_ratio_5': 1.5,
        'in_bowl_zone': True, 'j_low_enter': True, 'j_lift': True,
        'vol_attack': True, 'above_bbi': True, 'positive_candle': True,
        'market_cap_ok': True,
    }


@pytest.mark.parametrize('invalid_j', ['broken-number', object()], ids=['value-error', 'type-error'])
def test_zettaranc_invalid_indicator_is_not_no_match(invalid_j):
    row = _zettaranc_ready_row()
    row['J'] = invalid_j
    frame = pd.DataFrame([row] * MIN_HISTORY)
    with pytest.raises((TypeError, ValueError)):
        ZettarancComboStrategy().select_stocks(frame, '测试股份')


def test_zettaranc_normal_nan_and_threshold_filters_are_preserved():
    strategy = ZettarancComboStrategy()
    row = _zettaranc_ready_row()
    assert strategy._row_signal(pd.Series(row)) is True
    for column, value in [('J', float('nan')), ('J', 201.0), ('vol_attack', False)]:
        assert strategy._row_signal(pd.Series({**row, column: value})) is False

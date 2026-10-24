"""验证扫描日期窗口、逐策略终态及 B2 异常边界，避免漏算被伪装为未命中。"""

import pandas as pd
import pytest

from strategy.b2_strategy import B2Strategy
from web.backend.services import strategy_service as service


def _prices(count=500):
    dates = pd.bdate_range('2024-01-01', periods=count)[::-1]
    return pd.DataFrame({'date': dates.strftime('%Y-%m-%d'), 'close': 10.0})


class FakeStrategy:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def analyze_stock(self, code, name, df):
        if self.error:
            raise self.error
        return self.result


def test_historical_window_refills_after_date_cutoff(monkeypatch):
    full = _prices()
    target = full.iloc[173]['date']
    reads = []

    def read_stock(code, nrows=None):
        reads.append(nrows)
        return full.head(nrows).copy() if nrows else full.copy()

    monkeypatch.setattr(service.csv_manager, 'read_stock', read_stock)
    status, _, frame, _ = service._prepare_stock_context('688613', {'688613': '奥精医疗'}, target)
    assert status == 'ok'
    assert len(frame) == 320
    pd.testing.assert_frame_equal(frame, full.iloc[173:493].reset_index(drop=True))
    assert reads == [320, None]


def test_current_window_keeps_bounded_read(monkeypatch):
    full = _prices()
    reads = []

    def read_stock(code, nrows=None):
        reads.append(nrows)
        return full.head(nrows).copy()

    monkeypatch.setattr(service.csv_manager, 'read_stock', read_stock)
    result = service._prepare_stock_context('000001', {'000001': '平安银行'}, full.iloc[0]['date'])
    assert len(result[2]) == 320
    assert reads == [320]


def test_unreadable_nonempty_csv_is_error_not_insufficient_history(monkeypatch, tmp_path):
    stock_dir = tmp_path / '00'
    stock_dir.mkdir()
    (stock_dir / '000001.csv').write_text('broken payload', encoding='utf-8')
    monkeypatch.setattr(service.csv_manager, 'data_dir', tmp_path)
    monkeypatch.setattr(service.csv_manager, 'read_stock', lambda *args, **kwargs: pd.DataFrame())
    result = service._process_one_stock('000001', {'000001': '测试'}, [('b2', 'B2', FakeStrategy())])
    assert result['status'] == 'error'
    assert result['outcomes']['b2']['error_type'] == 'ValueError'


@pytest.mark.parametrize('target', ['not-a-date', '2026-02-30', '', '20260101'])
def test_invalid_target_date_is_rejected(target):
    with pytest.raises(ValueError):
        service._trim_price_frame_as_of(_prices(3), target)


@pytest.mark.parametrize('frame', [pd.DataFrame({'close': [1.0]}), pd.DataFrame({'date': ['broken']})])
def test_invalid_source_date_is_rejected(frame):
    with pytest.raises(ValueError):
        service._trim_price_frame_as_of(frame, '2026-01-01')


def test_mixed_date_strings_preserve_same_day_without_future():
    frame = pd.DataFrame({'date': ['2026-01-03', '2026-01-02 00:00:00', '2026-01-01']})
    trimmed = service._trim_price_frame_as_of(frame, '2026-01-02')
    assert trimmed['date'].tolist() == ['2026-01-02 00:00:00', '2026-01-01']


def test_per_strategy_outcomes_include_failures_and_remaining_results(monkeypatch):
    frame = _prices(60)
    monkeypatch.setattr(service, '_prepare_stock_context', lambda *args: ('ok', '测试', frame, None))
    monkeypatch.setattr(service, 'prepare_shared_indicators', lambda df, **kwargs: df)
    hit = {'code': '000001', 'name': '测试', 'signals': [{'date': frame.iloc[0]['date']}]}
    items = [('broken', '坏策略', FakeStrategy(error=ValueError('invalid metric'))),
             ('hit', '命中策略', FakeStrategy(result=hit)), ('miss', '未命中策略', FakeStrategy())]
    result = service._process_one_stock('000001', {'000001': '测试'}, items)
    assert result['status'] == 'error'
    assert set(result['hits']) == {'hit'}
    assert {key: value['status'] for key, value in result['outcomes'].items()} == {
        'broken': 'error', 'hit': 'matched', 'miss': 'not_matched'}
    assert result['outcomes']['broken']['error_type'] == 'ValueError'
    assert result['outcomes']['broken']['error_message'] == 'invalid metric'
    assert result['outcomes']['hit']['signal_count'] == 1


def test_prepare_failure_is_reported_for_every_strategy(monkeypatch):
    def fail(*args):
        raise ValueError('invalid date')

    monkeypatch.setattr(service, '_prepare_stock_context', fail)
    result = service._process_one_stock('000001', {'000001': '测试'}, [('b2', 'B2', FakeStrategy())])
    assert result['status'] == 'error'
    assert result['outcomes']['b2']['status'] == 'error'
    assert result['outcomes']['b2']['error_type'] == 'ValueError'


def test_skipped_stock_has_complete_outcomes(monkeypatch):
    monkeypatch.setattr(service, '_prepare_stock_context', lambda *args: ('skip', '测试', None, '数据不足'))
    result = service._process_one_stock('000001', {'000001': '测试'}, [('b2', 'B2', FakeStrategy())])
    assert result['status'] == 'skip'
    assert result['outcomes']['b2']['status'] == 'skipped'


def test_shared_indicator_failure_is_not_no_match(monkeypatch):
    monkeypatch.setattr(service, '_prepare_stock_context', lambda *args: ('ok', '测试', _prices(60), None))

    def fail(*args, **kwargs):
        raise ArithmeticError('bad indicator')

    monkeypatch.setattr(service, 'prepare_shared_indicators', fail)
    result = service._process_one_stock('000001', {'000001': '测试'}, [('b2', 'B2', FakeStrategy())])
    assert result['status'] == 'error'
    assert result['outcomes']['b2']['status'] == 'error'


def test_inline_failure_does_not_become_empty_signal_list(monkeypatch):
    monkeypatch.setattr(service, 'prepare_shared_indicators', lambda df, **kwargs: df)
    items = [('b2', 'B2', FakeStrategy(error=ValueError('bad template')))]
    with pytest.raises(RuntimeError, match='b2'):
        service.scan_one_stock_with_df('000001', _prices(60), {'000001': '测试'}, items)


def test_b2_template_error_is_propagated(monkeypatch):
    strategy = B2Strategy()
    monkeypatch.setattr(strategy.library, '_passes_fast_prefilter', lambda df: True)
    monkeypatch.setattr(strategy.library.analyzer, '_prepare_working_df', lambda code, df: df)

    def fail(*args):
        raise ArithmeticError('template failure')

    monkeypatch.setattr(strategy.library.analyzer, 'analyze_prepared', fail)
    with pytest.raises(ArithmeticError, match='template failure'):
        strategy.analyze_stock('300987', '川网传媒', _prices(60))


def test_b2_parallel_context_allows_absent_optional_damage_zone(monkeypatch):
    analyzer = B2Strategy().library.analyzer
    frame = pd.DataFrame({'date': ['2026-10-22', '2026-10-23'], 'J': [10.0, 30.0],
                          'close': [10.0, 11.0], 'low': [9.0, 10.0]})
    context = {
        'b1_result': {'idx': 0, 'date': '2026-10-22', 'j_val': 10.0},
        'consolidation': {'high': 10.0, 'low': 9.0, 'start': '2026-10-01', 'end': '2026-10-22'},
        'pattern_type': 'parallel_artillery', 'damage_zone': None,
    }
    monkeypatch.setattr(analyzer, '_build_pattern_context', lambda *args: context)
    monkeypatch.setattr(analyzer, '_detect_b2_breakout', lambda *args: {
        'idx': 1, 'date': '2026-10-23', 'pct_chg': 10.0, 'vol_ratio': 2.0})
    monkeypatch.setattr(analyzer, '_calc_hold_quality', lambda *args: (False, 0))
    result = analyzer.analyze_prepared('300987', frame, {})
    assert result['b2_date'] == '2026-10-23'
    assert result['pattern_type'] == 'parallel_artillery'
    assert result['damage_start'] is None


@pytest.mark.local_data
def test_300987_parallel_signal_survives_absent_damage_zone():
    status, _, frame, _ = service._prepare_stock_context('300987', {'300987': '川网传媒'}, '2026-10-23')
    if status != 'ok':
        pytest.skip('本地没有 300987 的案例行情')
    result = B2Strategy().analyze_stock('300987', '川网传媒', frame)
    assert result is not None
    signal = result['signals'][0]
    assert signal['date'] == '2026-09-17'
    assert signal['raw_result']['pattern_type'] == 'parallel_artillery'
    assert signal['raw_result']['damage_start'] is None


@pytest.mark.parametrize('indicator', ['zhixing', 'kdj'])
def test_b2_indicator_failure_reaches_stock_error_outcome(monkeypatch, indicator):
    from strategy import b2_strategy as b2
    frame = _prices(150)
    strategy = B2Strategy()
    monkeypatch.setattr(strategy.library, '_passes_fast_prefilter', lambda df: True)
    monkeypatch.setattr(service, '_prepare_stock_context', lambda *args: ('ok', '测试', frame, None))
    monkeypatch.setattr(service, 'prepare_shared_indicators', lambda df, **kwargs: df)
    monkeypatch.setattr(b2, 'has_cached_zhixing', lambda *args: False)
    monkeypatch.setattr(b2, 'has_cached_kdj', lambda *args: False)

    def fail(*args, **kwargs):
        raise ArithmeticError('indicator failure')

    monkeypatch.setattr(b2, 'calculate_zhixing_state', fail if indicator == 'zhixing' else lambda df: df)
    monkeypatch.setattr(b2, 'KDJ', fail)
    result = service._process_one_stock('000001', {'000001': '测试'}, [('b2', 'B2', strategy)])
    assert result['status'] == 'error'
    assert result['outcomes']['b2']['status'] == 'error'
    assert 'indicator failure' in result['outcomes']['b2']['error_message']

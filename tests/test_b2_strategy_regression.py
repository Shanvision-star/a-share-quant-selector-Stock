import pytest

from strategy.b2_strategy import B2Strategy
from utils.csv_manager import CSVManager
from web.backend.services.strategy_service import _trim_price_frame_as_of


@pytest.mark.local_data
def test_b2_classic_xinghuan_case_hits_on_breakout_date():
    df = _trim_price_frame_as_of(CSVManager('data').read_stock('688031'), '2025-12-05')

    result = B2Strategy().analyze_stock('688031', '星环科技-U', df)

    assert result is not None
    assert result['signals'][0]['date'] == '2025-12-05'

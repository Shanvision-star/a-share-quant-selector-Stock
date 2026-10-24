"""验证 MCP 只读策略结果分页、版本来源及参数边界，不建立研究或模型任务。"""
import asyncio
import pytest
from scripts import quant_mcp


def test_strategy_results_are_read_only_and_preserve_publication(monkeypatch):
    calls = []
    rows = [{'code': '000001', 'signal': {'date': '2026-10-23'}},
            {'code': '300987', 'signal': {'date': '2026-09-17'}}]

    def request(method, endpoint, payload=None):
        calls.append((method, endpoint, payload))
        return {'success': True, 'data': {'run_id': 'published', 'trade_date': '2026-10-23',
                'status': 'ready', 'source': 'sqlite', 'results': rows, 'total': 2}}

    monkeypatch.setattr(quant_mcp, 'request', request)
    result = quant_mcp.quant_strategy_results(trade_date='2026-10-23', offset=1, limit=1)
    assert result['data']['results'] == [rows[1]]
    assert result['data']['run_id'] == 'published'
    assert result['data']['total'] == 2
    assert result['data']['has_more'] is False
    assert calls == [('GET', 'strategy/results?strategy=all&date=2026-10-23', None)]
    tool = next(tool for tool in asyncio.run(quant_mcp.mcp.list_tools()) if tool.name == 'quant_strategy_results')
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.openWorldHint is False


@pytest.mark.parametrize('arguments', [
    {'trade_date': '2026-02-30'}, {'trade_date': '20261023'}, {'strategy': 'unknown'},
    {'limit': 0}, {'limit': 201}, {'offset': -1}, {'code': '../private'},
])
def test_invalid_result_query_never_reaches_backend(monkeypatch, arguments):
    calls = []
    monkeypatch.setattr(quant_mcp, 'request', lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        quant_mcp.quant_strategy_results(**arguments)
    assert calls == []


def test_stock_filter_keeps_total_and_signal_date(monkeypatch):
    monkeypatch.setattr(quant_mcp, 'request', lambda *args: {'success': True, 'data': {
        'total': 122, 'run_id': 'published', 'results': [
            {'code': '300987', 'date': '2026-09-17'}, {'code': '688613', 'date': '2026-10-23'}]}})
    data = quant_mcp.quant_strategy_results(code='300987')['data']
    assert data['total'] == 122
    assert data['filtered_total'] == 1
    assert data['results'] == [{'code': '300987', 'date': '2026-09-17'}]

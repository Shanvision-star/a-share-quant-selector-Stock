import argparse
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.akshare_fetcher import AKShareFetcher
from utils.csv_manager import CSVManager


def repair_code(fetcher: AKShareFetcher, csv_manager: CSVManager, code: str, years: int) -> tuple[bool, int]:
    existing = csv_manager.read_stock(code)
    if existing.empty:
        return False, 0

    refreshed = fetcher.fetch_stock_history(code, years=years)
    if refreshed is None or refreshed.empty:
        return False, 0

    existing = existing.copy()
    refreshed = refreshed.copy()
    existing['date'] = pd.to_datetime(existing['date'])
    refreshed['date'] = pd.to_datetime(refreshed['date'])

    metric_columns = ['date', 'amount', 'turnover', 'market_cap']
    refreshed = refreshed[metric_columns].drop_duplicates(subset=['date'], keep='first')
    merged = existing.merge(refreshed, on='date', how='left', suffixes=('', '__fresh'))
    for column in ['amount', 'turnover', 'market_cap']:
        if column in merged.columns:
            merged[column] = pd.to_numeric(merged[column], errors='coerce').fillna(0).astype(float)

    replaced_rows = 0
    for column in ['amount', 'turnover', 'market_cap']:
        fresh_column = f'{column}__fresh'
        if fresh_column not in merged.columns:
            continue

        current_values = pd.to_numeric(merged[column], errors='coerce').fillna(0)
        fresh_values = pd.to_numeric(merged[fresh_column], errors='coerce').fillna(0)
        should_replace = (current_values <= 0) & (fresh_values > 0)
        if column != 'market_cap':
            replaced_rows += int(should_replace.sum())
        merged.loc[should_replace, column] = merged.loc[should_replace, fresh_column]
        merged.drop(columns=[fresh_column], inplace=True)

    close_values = pd.to_numeric(merged['close'], errors='coerce').fillna(0)
    volume_values = pd.to_numeric(merged['volume'], errors='coerce').fillna(0)
    market_cap_values = pd.to_numeric(merged['market_cap'], errors='coerce').fillna(0)

    amount_values = pd.to_numeric(merged['amount'], errors='coerce').fillna(0)
    estimated_amount = close_values * volume_values * 100
    amount_missing = (amount_values <= 0) & (estimated_amount > 0)
    if amount_missing.any():
        merged.loc[amount_missing, 'amount'] = estimated_amount[amount_missing]
        replaced_rows += int(amount_missing.sum())

    turnover_values = pd.to_numeric(merged['turnover'], errors='coerce').fillna(0)
    estimated_turnover = (pd.to_numeric(merged['amount'], errors='coerce').fillna(0) / market_cap_values.replace(0, pd.NA) * 100).fillna(0)
    turnover_missing = (turnover_values <= 0) & (estimated_turnover > 0)
    if turnover_missing.any():
        merged.loc[turnover_missing, 'turnover'] = estimated_turnover[turnover_missing]
        replaced_rows += int(turnover_missing.sum())

    if replaced_rows == 0:
        return False, 0

    csv_manager.write_stock(code, merged)
    return True, replaced_rows


def main() -> None:
    parser = argparse.ArgumentParser(description='Backfill CSV amount/turnover columns with real historical values.')
    parser.add_argument('--codes', nargs='*', help='Specific stock codes to repair. If omitted, all existing CSV files are scanned.')
    parser.add_argument('--max-stocks', type=int, default=None, help='Limit number of scanned stocks.')
    parser.add_argument('--years', type=int, default=10, help='History years to request from the source.')
    args = parser.parse_args()

    fetcher = AKShareFetcher(str(PROJECT_ROOT / 'data'))
    csv_manager = CSVManager(str(PROJECT_ROOT / 'data'))

    codes = args.codes or csv_manager.list_all_stocks()
    if args.max_stocks:
        codes = codes[:args.max_stocks]

    updated = 0
    touched_rows = 0
    total = len(codes)

    for index, code in enumerate(codes, start=1):
        changed, row_count = repair_code(fetcher, csv_manager, code, years=args.years)
        if changed:
            updated += 1
            touched_rows += row_count
            print(f'[{index}/{total}] {code}: repaired {row_count} metric cells')
        else:
            print(f'[{index}/{total}] {code}: no repair needed')

    print(f'Completed. Updated files: {updated}, repaired cells: {touched_rows}')


if __name__ == '__main__':
    main()
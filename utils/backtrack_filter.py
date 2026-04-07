import sys
import os

# Add the project root directory to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

import argparse
import pandas as pd
from datetime import datetime
from strategy.b1_case_analyzer import B1CaseStrategy as B1Strategy
from strategy.bowl_rebound import BowlReboundStrategy
from strategy.b2_strategy import B2CaseAnalyzer

# Renaming file to avoid conflict
# utils/backtrack_filter.py
class BacktrackFilter:
    def __init__(self, data):
        self.data = data
        self.index = 0
        self.backtrack = []

    def backtrack(self):
        if self.index == 0:
            return None
        self.index -= 1
        return self.data[self.index]

    def next(self):
        if self.index < len(self.data):
            result = self.data[self.index]
            self.index += 1
            return result
        raise StopIteration

    def reset(self):
        self.index = 0
        self.backtrack = []

    def __iter__(self):
        return self

    def __next__(self):
        if self.index < len(self.data):
            result = self.data[self.index]
            self.index += 1
            return result
        raise StopIteration

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        if index < len(self.data):
            return self.data[index]
        raise IndexError

    def __str__(self):
        return str(self.data)

    def __repr__(self):
        return f"BacktrackFilter({self.data})"

def load_stock_data(stock_code):
    # Assuming data is stored in data/00/000001.csv format
    file_path = f"data/{stock_code[:2]}/{stock_code}.csv"
    try:
        data = pd.read_csv(file_path)
        data['date'] = pd.to_datetime(data['date'])  # Ensure date column is in datetime format
        return data
    except FileNotFoundError:
        print(f"Error: Data file for stock {stock_code} not found.")
        return None

def filter_data_by_date(data, start_date, end_date):
    start_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_date = datetime.strptime(end_date, "%Y-%m-%d")
    return data[(data['date'] >= start_date) & (data['date'] <= end_date)]

def analyze_b1_strategy(record):
    """
    Analyze if a single record satisfies the B1 strategy.
    :param record: A dictionary containing stock data for a single day.
    :return: True if the record satisfies the B1 strategy, False otherwise.
    """
    b1_analyzer = B1Strategy()
    df = pd.DataFrame([record])  # Convert record to DataFrame for analysis
    analysis_result = b1_analyzer.analyze(df)
    return analysis_result.get('passed', False)

def analyze_bowl_strategy(record):
    """
    Analyze if a single record satisfies the Bowl Rebound strategy.
    :param record: A dictionary containing stock data for a single day.
    :return: True if the record satisfies the Bowl Rebound strategy, False otherwise.
    """
    bowl_strategy = BowlReboundStrategy()
    df = pd.DataFrame([record])  # Convert record to DataFrame for strategy analysis
    indicators = bowl_strategy.calculate_indicators(df)
    return indicators.iloc[0]['abnormal']  # Check if the record satisfies the strategy

def analyze_b2_strategy(record):
    """
    Analyze if a single record satisfies the B2 strategy.
    :param record: A dictionary containing stock data for a single day.
    :return: True if the record satisfies the B2 strategy, False otherwise.
    """
    b2_analyzer = B2CaseAnalyzer()
    if 'code' not in record:
        return False  # Return False if 'code' key is missing
    df = pd.DataFrame([record])  # Convert record to DataFrame for strategy analysis
    result = b2_analyzer.analyze(record['code'], df, B2CaseAnalyzer.DEFAULT_PARAMS)
    return result is not None

def main():
    parser = argparse.ArgumentParser(description="Backtrack Filter Script")
    parser.add_argument("--stock_code", type=str, required=True, help="Stock code to analyze")
    parser.add_argument("--start_date", type=str, required=True, help="Start date for analysis (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, required=True, help="End date for analysis (YYYY-MM-DD)")

    args = parser.parse_args()

    print(f"Analyzing stock {args.stock_code} from {args.start_date} to {args.end_date}")

    # Load stock data
    data = load_stock_data(args.stock_code)
    if data is None:
        return

    # Filter data by date range
    filtered_data = filter_data_by_date(data, args.start_date, args.end_date)
    if filtered_data.empty:
        print("No data available for the specified date range.")
        return

    # Perform backtracking analysis
    backtrack_filter = BacktrackFilter(filtered_data.to_dict('records'))
    print("Starting backtracking analysis...")

    strategy_results = []

    for record in backtrack_filter:
        b1_result = analyze_b1_strategy(record)
        bowl_result = analyze_bowl_strategy(record)
        b2_result = analyze_b2_strategy(record)

        if b1_result:
            strategy_results.append((record['date'], 'B1'))
        elif bowl_result:
            strategy_results.append((record['date'], 'Bowl Rebound'))
        elif b2_result:
            strategy_results.append((record['date'], 'B2'))

    if strategy_results:
        print("Dates and strategies satisfied:")
        for date, strategy in strategy_results:
            print(f"{date}: {strategy}")
    else:
        print("No strategies were satisfied in the given date range.")

if __name__ == "__main__":
    main()
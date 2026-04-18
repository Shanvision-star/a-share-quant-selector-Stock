import sqlite3

def check_strategy_results_count(trade_date):
    db_path = "d:/stock/20260329dingtalk/a-share-quant-selector-main-zuozhe/a-share-quant-selector-Stock/data/strategy_results.db"
    query = "SELECT COUNT(*) FROM strategy_results WHERE trade_date = ?;"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query, (trade_date,))
        count = cursor.fetchone()[0]
        print(f"Total records for trade_date {trade_date}: {count}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    trade_date = "2026-04-10"  # Replace with the desired trade date
    check_strategy_results_count(trade_date)
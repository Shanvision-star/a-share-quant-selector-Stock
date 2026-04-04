# B2 Strategy Changelog

## Overview
This document outlines the changes made to the project to implement the B2 strategy, along with the relevant execution commands and their explanations.

---

## Code Changes

### 1. `strategy/b2_strategy.py`
- **Purpose**: Implements the B2 strategy logic.
- **Key Additions**:
  - `B2CaseAnalyzer`: Analyzes individual stocks based on the B2 strategy.
  - `B2PatternLibrary`: Manages and executes the B2 strategy.

### 2. `strategy/pattern_config.py`
- **Purpose**: Stores B2 strategy cases and default parameters.
- **Key Additions**:
  - `B2_PERFECT_CASES`: Stores the perfect cases for evaluating the B2 strategy.
  - `B2_DEFAULT_PARAMS`: Contains default parameters for the B2 strategy.

### 3. `utils/dingtalk_notifier.py`
- **Purpose**: Sends notifications for strategy results.
- **Key Additions**:
  - `send_b2_match_results()`: Sends B2 strategy results via DingTalk.

### 4. `main.py`
- **Purpose**: Integrates B2 strategy execution into the main workflow.
- **Key Additions**:
  - Added `--b2-match` command-line argument to trigger the B2 strategy.

### 5. `quant_system.py`
- **Purpose**: Executes the B2 strategy.
- **Key Additions**:
  - `run_with_b2_match()`: Executes the B2 strategy logic.

---

## Execution Commands

### 1. Run the B2 Strategy
```bash
python main.py run --b2-match
```
- **Description**: Executes the B2 strategy for all stocks in the dataset.

### 2. Run the B2 Strategy with Limited Stocks
```bash
python main.py run --b2-match --max-stocks 5
```
- **Description**: Executes the B2 strategy for a maximum of 5 stocks.

### 3. Verify B2 Strategy Import
```bash
.\.venv\Scripts\python.exe -c "from strategy.b2_strategy import B2CaseAnalyzer, B2PatternLibrary; print('B2 导入成功')"
```
- **Description**: Verifies that the `B2CaseAnalyzer` and `B2PatternLibrary` classes are correctly imported.

---

## Notes
- Ensure that the virtual environment is activated before running the commands.
- Use the `--max-stocks` argument to limit the number of stocks processed for testing purposes.
- Check the DingTalk notifications for results when using `send_b2_match_results()`.
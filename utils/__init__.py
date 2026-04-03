"""
工具模块

提供数据获取、技术指标计算、通知推送、图表生成和文件导出等核心功能。

子模块说明：
    akshare_fetcher   - AKShare 数据抓取（含并发处理）
    csv_manager       - CSV 文件读写管理
    technical         - 技术指标计算（MA / EMA / KDJ 等）
    dingtalk_notifier - 钉钉推送（含限流与图片上传）
    kline_chart       - K 线图生成（matplotlib）
    kline_chart_fast  - 快速 K 线图生成
    tdx_exporter      - 通达信格式导出
    backtrack_analyzer - 3 天回溯分析
"""

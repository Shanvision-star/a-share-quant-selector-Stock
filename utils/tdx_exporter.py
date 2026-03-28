from pathlib import Path
from datetime import datetime


class TdxExporter:
    """
    通达信导出器

    主要功能：
    1. 把股票代码转换成通达信可导入的格式
    2. 导出为 txt 文件
    3. 自动生成带日期时间的历史归档文件
    4. 同时生成一个固定名称的 latest 文件，方便你直接导入
    """

    @staticmethod
    def normalize_code(code: str) -> str:
        """
        规范化股票代码，统一补齐为 6 位字符串

        例如：
        7 -> 000007
        131 -> 000131
        600131 -> 600131
        """
        return str(code).strip().zfill(6)

    @classmethod
    def to_tdx_code(cls, code: str) -> str:
        """
        将普通股票代码转换成通达信导入格式

        规则：
        - 沪市：前面加 1
        - 深市：前面加 0

        示例：
        600131 -> 1600131
        000007 -> 0000007
        300179 -> 0300179

        注意：
        这里必须返回字符串，不能转成数字，
        否则前导 0 会丢失。
        """
        code = cls.normalize_code(code)

        # 常见沪市股票代码前缀
        if code.startswith(("600", "601", "603", "605", "688", "900")):
            return f"1{code}"

        # 其余默认按深市处理
        return f"0{code}"

    @staticmethod
    def sanitize_name(name: str) -> str:
        """
        清理股票名称中的首尾空格
        """
        return str(name).strip()

    @classmethod
    def build_lines(cls, stocks):
        """
        把股票列表转换成通达信 txt 文件的每一行内容

        输入示例：
        [
            {"code": "600131", "name": "国网信通"},
            {"code": "300179", "name": "四方达"}
        ]

        输出示例：
        [
            "1600131,国网信通",
            "0300179,四方达"
        ]
        """
        seen = set()
        lines = []

        for stock in stocks:
            # 读取股票代码和名称
            code = cls.normalize_code(stock.get("code", ""))
            name = cls.sanitize_name(stock.get("name", ""))

            # 如果代码为空，则跳过
            if not code:
                continue

            # 去重，避免重复导出同一只股票
            if code in seen:
                continue
            seen.add(code)

            # 转成通达信格式代码
            tdx_code = cls.to_tdx_code(code)

            # 拼接成一行：市场标识+股票代码,股票名称
            lines.append(f"{tdx_code},{name}")

        return lines

    @classmethod
    def export_txt(
        cls,
        stocks,
        output_dir="output/tdx",
        filename=None,
        write_latest=True,
        latest_filename="tdx_stocks_latest.txt",
    ):
        """
        导出通达信 txt 文件

        参数说明：
        - stocks: 股票列表
        - output_dir: 输出目录，默认 output/tdx
        - filename: 历史归档文件名；如果不传，则自动生成带时间的文件名
        - write_latest: 是否额外生成 latest 文件
        - latest_filename: latest 文件名

        返回：
        {
            "file_path": "历史归档文件路径",
            "latest_path": "latest 文件路径",
            "count": 导出数量
        }
        """
        # 创建输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # 如果没有传入历史文件名，则自动生成带日期时间的文件名
        if filename is None:
            # 例如：20260326_153025
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"tdx_stocks_{ts}.txt"

        # 历史归档文件路径
        archive_path = output_path / filename

        # latest 文件路径
        latest_path = output_path / latest_filename

        # 生成通达信导出内容
        lines = cls.build_lines(stocks)

        # 用换行符拼接成完整文本内容
        content = "\n".join(lines)

        # 写入历史归档文件
        archive_path.write_text(content, encoding="utf-8-sig")

        # 如果需要，同时写入 latest 文件
        if write_latest:
            latest_path.write_text(content, encoding="utf-8-sig")
            latest_path_str = str(latest_path)
        else:
            latest_path_str = None

        # 返回导出结果，方便主程序打印日志
        return {
            "file_path": str(archive_path),
            "latest_path": latest_path_str,
            "count": len(lines),
        }
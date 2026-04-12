# 转换文件编码为 UTF-8
import os

file_path = 'utils/tdx_exporter.py'
temp_path = 'utils/temp_tdx_exporter.py'

try:
    # 读取文件内容
    with open(file_path, 'r', encoding='gbk') as f:
        content = f.read()

    # 写入到临时文件
    with open(temp_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # 替换原文件
    os.remove(file_path)
    os.rename(temp_path, file_path)

    print(f"Successfully converted {file_path} to UTF-8.")
except Exception as e:
    print(f"Error converting file: {e}")
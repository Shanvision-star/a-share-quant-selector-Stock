import os
from ctypes import cdll
from EmQuantAPI import *

def main_callback(quantdata):
    print("Callback:", quantdata)

# 手动加载 EmQuantAPI.dll
dll_path = r"E:\ApplicationInstall\EMQuantAPI_Python\python3\libs\windows\EmQuantAPI.dll"  # 替换为实际路径
if not os.path.exists(dll_path):
    raise FileNotFoundError(f"未找到 EmQuantAPI.dll 文件，请检查路径：{dll_path}")

cdll.LoadLibrary(dll_path)

# 登录 EmQuantAPI
login_result = c.start("ForceLogin=1", main_callback)
if login_result.ErrorCode != 0:
    print("登录失败，错误代码：", login_result.ErrorCode)
    exit()

# 获取实时行情数据
data = c.cst("000001.SZ,600000.SH", "NAME,OPEN,HIGH,LOW,LAST", "RowIndex=1,Ispandas=1")
print(data)

# 关闭 API
c.stop()
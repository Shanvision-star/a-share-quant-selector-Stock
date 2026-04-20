import ctypes
from EmQuantAPI import c

# Step 1: Directly specify the DLL path
def load_dll():
    dll_path = r"E:\\ApplicationInstall\\EMQuantAPI_Python\\python3\\libs\\windows\\EmQuantAPI_x64.dll"
    try:
        ctypes.CDLL(dll_path)
        print("DLL loaded successfully from specified path.")
    except OSError as e:
        print(f"Failed to load DLL: {e}")

# Step 2: Test API functionality
def test_api():
    try:
        # Create an instance of EmQuantData
        data = c.EmQuantData()
        data.ErrorCode = 0
        data.ErrorMsg = "Test success"
        data.Codes = ["000001.SZ"]
        data.Indicators = ["Close"]
        data.Dates = ["2026-04-21"]
        data.Data = {"000001.SZ": [10.5]}

        print("EmQuantData instance created successfully:")
        print(data)
    except Exception as e:
        print(f"Failed to test API functionality: {e}")

if __name__ == "__main__":
    # Load DLL
    load_dll()

    # Test API functionality
    test_api()
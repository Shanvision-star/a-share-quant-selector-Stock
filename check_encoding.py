import os
import chardet

def check_file_encoding(file_path):
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
            result = chardet.detect(raw_data)
            return result['encoding']
    except Exception as e:
        return f"Error: {e}"

def check_all_files_encoding(base_dir):
    for root, _, files in os.walk(base_dir):
        for file in files:
            file_path = os.path.join(root, file)
            encoding = check_file_encoding(file_path)
            print(f"{file_path}: {encoding}")

if __name__ == "__main__":
    base_directory = os.path.dirname(os.path.abspath(__file__))
    check_all_files_encoding(base_directory)
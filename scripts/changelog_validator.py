import re

def validate_changelog(file_path):
    """Validate the changelog file for formatting issues."""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    issues = []
    for i, line in enumerate(lines, start=1):
        if line.startswith('- '):
            # Check for emoji at the start
            if not re.match(r'- \p{So}', line):
                issues.append(f"Line {i}: Missing emoji at the start of the entry.")

            # Check for action verb
            if not re.search(r'(Add|Fix|Update|Remove|Improve)', line):
                issues.append(f"Line {i}: Missing action verb.")

            # Check for component/module name
            if not re.search(r'\*\*\w+\*\*', line):
                issues.append(f"Line {i}: Missing component/module name.")

    return issues

def main():
    file_path = input("Enter the path to the changelog file: ")
    issues = validate_changelog(file_path)

    if issues:
        print("Validation issues found:")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("Changelog file is valid.")

if __name__ == "__main__":
    main()
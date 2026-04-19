import subprocess
import re
from datetime import datetime

def get_tags():
    """Fetch and return a list of tags sorted by version."""
    result = subprocess.run(['git', 'tag', '--list'], capture_output=True, text=True)
    tags = result.stdout.splitlines()
    tags = [tag for tag in tags if not re.search(r'(experimental|alpha|resource)', tag)]
    tags.sort(key=lambda x: [int(num) for num in re.split(r'\.|-', x) if num.isdigit()])
    return tags

def get_commits_between_tags(from_tag, to_tag):
    """Fetch commits between two tags."""
    result = subprocess.run(['git', 'log', f'{from_tag}..{to_tag}', '--oneline'], capture_output=True, text=True)
    commits = result.stdout.splitlines()
    return commits

def extract_pr_numbers(commits):
    """Extract PR numbers from commit messages."""
    pr_numbers = []
    for commit in commits:
        match = re.search(r'#(\d+)', commit)
        if match:
            pr_numbers.append(match.group(1))
    return pr_numbers

def main():
    tags = get_tags()
    print("Available tags:")
    for i, tag in enumerate(tags):
        print(f"{i + 1}. {tag}")

    from_index = int(input("Select the starting tag (by number): ")) - 1
    to_index = int(input("Select the ending tag (by number): ")) - 1

    from_tag = tags[from_index]
    to_tag = tags[to_index]

    print(f"Fetching commits between {from_tag} and {to_tag}...")
    commits = get_commits_between_tags(from_tag, to_tag)

    print("Extracting PR numbers...")
    pr_numbers = extract_pr_numbers(commits)
    print(f"Found PRs: {', '.join(pr_numbers)}")

    with open("~changelog.md", "w", encoding="utf-8") as f:
        f.write(f"# Changelog\n\n")
        f.write(f"## Version: {to_tag}\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        for pr in pr_numbers:
            f.write(f"- PR #{pr}\n")

    print("Changelog draft written to ~changelog.md")

if __name__ == "__main__":
    main()
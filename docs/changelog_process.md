# Changelog Process Documentation

This document outlines the process for managing changelogs in the A-Share Quant Selector project.

## Overview
The changelog process ensures that all notable changes are documented in a structured and consistent manner. This includes new features, bug fixes, optimizations, and other updates.

## Steps

### 1. Commit Messages
- Follow the [Commit Message Template](commit_pr_templates.md) to ensure all commits are properly categorized.
- Include a clear description of the change and its impact.

### 2. Pull Requests
- Use the [PR Description Template](commit_pr_templates.md) to document changes in both English and Chinese.
- Ensure the PR description includes changelog entries.

### 3. Changelog Draft Generation
- Use the `changelog_generator.py` script to generate a draft changelog:
  ```bash
  python scripts/changelog_generator.py
  ```
- Select the starting and ending tags to fetch commits and PRs.
- Review the generated `~changelog.md` file.

### 4. Validation
- Validate the changelog file using the `changelog_validator.py` script:
  ```bash
  python scripts/changelog_validator.py docs/CHANGELOG.md
  ```
- Fix any issues reported by the validator.

### 5. Finalization
- Append the validated changelog entries to `docs/CHANGELOG.md`.
- Ensure the changelog is updated in both English and Chinese.

### 6. CI/CD Integration
- The changelog validation and generation scripts are integrated into the CI/CD pipeline.
- On every pull request, the pipeline will:
  - Validate the `docs/CHANGELOG.md` file.
  - Generate a draft changelog if necessary.

## Examples

### Commit Message Example
```
feat(strategy): add support for new bowl rebound classification

Added new classification logic to the bowl rebound strategy, including support for `duokong_pct` and `short_pct` parameters.
```

### PR Description Example
#### English
```
- 🆕 Feature: Add support for new bowl rebound classification.
- 🐞 Fix: Corrected calculation error in trend analysis.
```

#### Chinese
```
- 🆕 新功能: 添加对碗口反弹分类的新支持。
- 🐞 修复: 修正趋势分析中的计算错误。
```

## Notes
- Always run the validation script before finalizing the changelog.
- Ensure all entries are clear, concise, and follow the defined format.

For more details, refer to the [Commit and PR Templates](commit_pr_templates.md).
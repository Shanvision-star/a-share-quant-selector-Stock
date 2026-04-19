# Commit Message and PR Description Templates

## Commit Message Template

```
<type>(<scope>): <short description>

[Optional] <longer description>

[Optional] BREAKING CHANGE: <description of breaking change>
```

### Types
- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation only changes
- **style**: Changes that do not affect the meaning of the code (white-space, formatting, etc.)
- **refactor**: A code change that neither fixes a bug nor adds a feature
- **perf**: A code change that improves performance
- **test**: Adding missing tests or correcting existing tests
- **chore**: Changes to the build process or auxiliary tools and libraries

### Example
```
feat(strategy): add support for new bowl rebound classification

Added new classification logic to the bowl rebound strategy, including support for `duokong_pct` and `short_pct` parameters.
```

---

## PR Description Template

### Summary
Provide a brief summary of the changes in this PR.

### Changelog Entry
Include changelog entries in both English and Chinese:

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

### Checklist
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] Changelog updated

---
# git_push_guide.md

# Git 本地代码推送到 GitHub 远端仓库完整操作指南

适用场景：本地代码已修改/更新，需提交并推送到个人 GitHub 仓库（适配本人仓库配置）

## 一、前置配置说明（本人专属）

- 远程仓库名称（remote name）：**Shanvision-star**（非默认 origin，核心注意点）

- 推送分支：**master**

- 代理配置（Clash）：地址 127.0.0.1，端口 7890（解决 GitHub 连接失败）

- 本人 GitHub 仓库地址：https://github.com/Shanvision-star/a-share-quant-selector-Stock

## 二、完整推送流程（按顺序执行）

### 步骤 1：查看本地代码修改状态（可选，确认修改内容）

```bash
git status
```

说明：执行后会显示本地已修改、未暂存的文件，确认无误后进入下一步。

### 步骤 2：将所有修改添加到暂存区

```bash
git add .
```

说明：`git add .` 表示添加当前目录下所有修改/新增/删除的文件，若需添加单个文件，替换 `.` 为具体文件名。

### 步骤 3：提交修改到本地仓库（必须填写备注）

```bash
git commit -m "本次更新内容说明"
```

示例：`git commit -m "加入B2策略配置策略钉钉推送"`，备注需简洁明了，说明本次更新的核心内容。

### 步骤 4：配置 Git 代理（解决 GitHub 连接超时，关键步骤）

```bash
# 先清除旧的代理配置（避免冲突）
git config --global --unset http.proxy
git config --global --unset https.proxy

# 配置 Clash 代理（适配本人代理端口）
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
```

### 步骤 5：推送到 GitHub 远端仓库

```bash
git push -u Shanvision-star master
```

说明：首次推送需加 `-u`，绑定远程仓库和分支，后续推送可直接简化为 `git push Shanvision-star master`。

## 三、常见报错及解决方案（本人已遇到，亲测有效）

### 报错 1：远程分支版本较新，推送被拒绝

```bash
hint: Updates were rejected because the tip of your current branch is behind
hint: its remote counterpart. If you want to integrate the remote changes,
hint: use 'git pull' before pushing again.
```

解决方案：先拉取远程最新代码，合并冲突后再推送

```bash
# 拉取远程 master 分支代码，允许无关历史合并
git pull Shanvision-star master --allow-unrelated-histories

# 拉取后若提示冲突（如 README.md 冲突），打开冲突文件
# 删除冲突标记（<<<<<<< HEAD、=======、>>>>>>> Shanvision-star/master），保留需要的内容，保存文件

# 重新暂存、提交、推送
git add .
git commit -m "解决分支冲突，合并远程代码"
git push -u Shanvision-star master
```

### 报错 2：Git 无法连接 GitHub（端口 443 连接失败）

```bash
fatal: unable to access 'https://github.com/Shanvision-star/a-share-quant-selector-Stock/': Failed to connect to github.com port 443 after 21114 ms: Could not connect to server
```

解决方案：

- 确认 Clash 已连接，系统代理已开启；

- 重新执行步骤 4 的代理配置命令；

- 若仍失败，将 Clash 模式从「规则」切换为「全局（Global）」，再重新推送。

### 报错 3：origin 不存在（远程名称错误）

```bash
fatal: 'origin' does not appear to be a git repository
fatal: Could not read from remote repository.
```

解决方案：本人远程仓库名称为 `Shanvision-star`，而非默认 `origin`，推送时使用正确的远程名称，执行：

```bash
git push -u Shanvision-star master
```

## 四、日常快速推送简化流程（推送成功后常用）

```bash
# 1. 添加修改到暂存区
git add .

# 2. 提交到本地仓库
git commit -m "更新内容备注"

# 3. 推送到远端
git push Shanvision-star master
```

## 五、辅助命令（常用排查）

- 查看远程仓库配置（确认远程名称和地址）：`git remote -v`

- 验证 Git 代理配置是否生效：
        `git config --global --get http.proxy
git config --global --get https.proxy`
        若显示 `http://127.0.0.1:7890`，说明代理配置成功。
      

- 取消 Git 代理配置（无需代理时使用）：
        `git config --global --unset http.proxy
git config --global --unset https.proxy`

## 六、注意事项

- 每次推送前，建议先执行 `git pull` 拉取远程最新代码，避免冲突；

- 提交备注需规范，便于后续查看更新记录；

- 代理配置仅需执行一次，后续推送无需重复配置（除非更换代理或清除配置）；

- 若推送时提示输入 GitHub 账号密码，输入本人 GitHub 账号和授权 Token 即可（Token 需提前在 GitHub 账号中创建）。
> （注：文档部分内容可能由 AI 生成）
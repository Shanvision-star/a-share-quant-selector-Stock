# Git 操作文档：本地 ↔ GitHub ↔ 云服务器
适用场景：本地代码上传 GitHub、GitHub 代码拉取到本地、云服务器同步最新代码
文档版本：v1.0 | 更新时间：2026-03-29

---

## 一、准备工作（首次必做）
### 1. 安装 Git
下载地址：https://git-scm.com/
安装默认下一步即可。

### 2. 配置 Git 身份（仅第一次）
git config --global user.name "你的GitHub用户名"
git config --global user.email "你的GitHub邮箱"

### 3. 查看配置
git config --list

---

## 二、场景 1：本地代码 → 上传到 GitHub
### 方式 A：首次上传（本地已有代码）
# 1. 进入项目文件夹
cd D:\stock\a-share-quant-selector-main1\Dingtalk\a-share-quant-selector-Stock

# 2. 初始化 Git
git init

# 3. 添加所有文件
git add .

# 4. 提交本地
git commit -m "首次提交项目"

# 5. 关联远程仓库
git remote add origin https://github.com/Shanvision-star/a-share-quant-selector-Stock.git

# 6. 推送到 GitHub
git push -u origin main

### 方式 B：修改后再次上传（日常使用）
git add .
git commit -m "更新内容说明"
git push origin main

---

## 三、场景 2：GitHub 代码 → 下载到本地
### 方式 1：全新克隆（第一次下载）
git clone https://github.com/Shanvision-star/a-share-quant-selector-Stock.git

### 方式 2：已有项目，拉取最新更新
cd a-share-quant-selector-Stock
git pull origin main

---

## 四、场景 3：云服务器 → 同步 GitHub 代码
### 1. 服务器第一次拉取
git clone https://github.com/Shanvision-star/a-share-quant-selector-Stock.git

### 2. 服务器更新最新代码（每次 GitHub 更新后执行）
cd a-share-quant-selector-Stock
git pull origin main

---

## 五、高频命令速查
git clone 地址      # 下载项目
git add .          # 添加所有修改
git commit -m "备注" # 提交本地
git push           # 上传到 GitHub
git pull           # 拉取最新代码
git status         # 查看文件状态
git log            # 查看提交记录
git remote -v      # 查看远程地址

---

## 六、常见问题解决
### 1. 权限报错 Permission denied
git remote set-url origin https://github.com/Shanvision-star/a-share-quant-selector-Stock.git
git push

### 2. 网络失败 Connection reset
使用加速镜像：
git clone https://github.com.cnpmjs.org/Shanvision-star/a-share-quant-selector-Stock.git

### 3. 合并未完成 MERGE_HEAD exists
git merge --abort
git pull

---

## 七、完整流程总结
1. 本地 → GitHub：add → commit → push
2. GitHub → 本地：clone / pull
3. GitHub → 云服务器：clone / pull
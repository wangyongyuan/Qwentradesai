# Git 推送指南

## 当前状态

- ✅ Git 仓库已初始化
- ✅ 代码已提交（51个文件，9633行代码）
- ✅ 远程仓库已配置：`https://github.com/wangyongyuan/Qwentradesai.git`
- ✅ 分支：`main`

## 推送方法

### 方法一：使用 Token 在 URL 中（推荐）

```bash
cd /Users/gufii/QwenTradeAI

# 使用 Token 配置远程仓库（将 YOUR_TOKEN 替换为你的实际Token）
git remote set-url origin https://YOUR_TOKEN@github.com/wangyongyuan/Qwentradesai.git

# 推送代码
git push -u origin main
```

### 方法二：手动输入（如果方法一失败）

```bash
cd /Users/gufii/QwenTradeAI

# 推送代码
git push -u origin main
```

当提示输入时：
- **Username**: `wangyongyuan`
- **Password**: `你的GitHub Personal Access Token`（不是GitHub密码）

### 方法三：使用 SSH（如果配置了 SSH 密钥）

```bash
# 切换到 SSH 地址
git remote set-url origin git@github.com:wangyongyuan/Qwentradesai.git

# 推送
git push -u origin main
```

## 验证推送

推送成功后，访问：
https://github.com/wangyongyuan/Qwentradesai

## 常见问题

### 1. 403 错误
- 检查 Token 是否有 `repo` 权限
- 确认 Token 未过期
- 重新生成 Token：https://github.com/settings/tokens

### 2. 网络连接问题
- 检查网络连接
- 如果在中国，可能需要配置代理
- 尝试使用 SSH 方式

### 3. 仓库不存在
- 确认仓库地址正确
- 在 GitHub 上创建仓库：https://github.com/new
- 仓库名：`Qwentradesai`

## 后续操作

推送成功后，每次修改代码后：

```bash
# 1. 查看修改
git status

# 2. 添加修改
git add .

# 3. 提交
git commit -m "描述你的修改"

# 4. 推送
git push
```


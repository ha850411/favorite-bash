# Favorite Bash & Zsh Scripts

個人常用的自定義 Shell 指令與自動化工具集合。

## 指令列表

### 1. `pr-review`
批次審核並 Approve 指定的 GitHub Pull Request 網址。

**使用方式：**
```bash
# 帶入一至多個 PR 網址
pr-review https://github.com/owner/repo/pull/1 https://github.com/owner/repo/pull/2

# 透過 Pipe 輸入
cat urls.txt | pr-review

# 直接執行（將自動從 macOS 剪貼簿讀取網址）
pr-review
```

---

### 2. `pr-reviews`
透過 GitHub GraphQL API 搜尋指派給你的待審核 PR，並提供互動式 TUI 卡片選單進行批次 Approve。

**使用方式：**
```bash
pr-reviews
```

**操作快捷鍵：**
- `↑` / `k`: 上移選擇
- `↓` / `j`: 下移選擇
- `Space`: 勾選 / 取消勾選單一 PR
- `a`: 全選 / 全部取消
- `Enter`: 執行批次 Approve
- `q`: 離開選單

---

## 本機連結設定

本專案的 `bin/pr-review` 與 `bin/pr-reviews` 軟連結（symlink）至本機 `~/.local/bin/`：

```bash
ln -sf /Volumes/workspace/favorite-bash/bin/pr-review ~/.local/bin/pr-review
ln -sf /Volumes/workspace/favorite-bash/bin/pr-reviews ~/.local/bin/pr-reviews
```

或是於 `~/.zshrc` 中引用：

```zsh
source /Volumes/workspace/favorite-bash/pr-review.zsh
```

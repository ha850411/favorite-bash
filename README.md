# Favorite Bash & Zsh Scripts

個人常用的自定義 Shell 指令與自動化工具集合。

## 🚀 快速安裝 / 卸載

### 一鍵安裝
在專案根目錄下執行：
```bash
./install.sh
```
此動作會：
1. 將 `bin/` 下所有指令軟連結（symlink）至 `~/.local/bin/`。
2. 自動將 `pr-review.zsh` 引用路徑寫入 `~/.zshrc`（如尚未寫入）。

### 一鍵卸載
在專案根目錄下執行：
```bash
./uninstall.sh
```
此動作會：
1. 移除 `~/.local/bin/` 中屬於本專案的指令軟連結。
2. 清理 `~/.zshrc` 中的引用設定。

---

## 🛠 指令列表

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

### 3. `pr-merge`
快速預覽並開立 PR 將 Branch A 合併至 Branch B。若目標 Branch B 不存在，自動在遠端建立 Branch B。

**使用方式：**
```bash
# 基本用法：指定來源分支 A 與目標分支 B
pr-merge feature/login release/v1.0

# 指定 Target Branch B 不存在時所使用的 Base 分支
pr-merge feature/login release/v1.0 -b develop

# 指定特定 GitHub Repository
pr-merge -r owner/repo feature/login release/v1.0

# 自動確認預覽直接開 PR
pr-merge feature/login release/v1.0 -y

# 編輯設定檔（設定要追蹤的 Repo 與預設 Base 分支）
pr-merge config
```

**設定檔說明：**
設定檔優於專案目錄下搜尋 (`pr-merge.json` 或 `.pr-merge.json`)：
```json
{
  "default_target_base": "main",
  "repos": {
    "owner/frontend-app": {
      "default_base": "main",
      "branch_rules": [
        { "pattern": "release/hotfix/*", "base": "main" },
        { "pattern": "release/*", "base": "develop" }
      ]
    },
    "owner/backend-api": {
      "default_base": "develop",
      "branch_rules": [
        { "pattern": "release/v1.*", "base": "v1-legacy" },
        { "pattern": "release/v2.*", "base": "main" }
      ]
    }
  }
}
```
- `default_target_base`: 全域備用 Base 分支。
- `repos`: 針對不同 GitHub Repositories 個別設定：
  - `default_base`: 該 Repo 預設的 Base 分支。
  - `branch_rules`: 針對該 Repo 內不同的 Target Branch 通配符 Match Pattern (例如 `release/hotfix/*` 或 `release/*`)，各自指定要使用的 Base 分支。



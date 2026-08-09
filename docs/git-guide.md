# Git 操作说明书

本文档面向对 Git 不熟悉的团队成员，按照实际操作顺序说明每一步。

---

## 一、首次加入项目

### 1. 安装 Git

去 https://git-scm.com/download/win 下载安装，一路 Next 即可。

安装后打开命令行（Win + R → 输入 `cmd`），验证：

```bash
git --version
# 输出类似：git version 2.45.0
```

### 2. 配置身份（每台电脑只需做一次）

```bash
git config --global user.name "你的名字"
git config --global user.email "你的邮箱@example.com"
```

> 邮箱填你 GitHub 账号绑定的邮箱。

### 3. 克隆项目

```bash
git clone https://github.com/wxl-0/trusted-rag-banking.git
cd trusted-rag-banking
```

### 4. 切换并同步 main

`main` 是项目唯一最新基线和默认开发分支。克隆完成后，切换并更新 `main`：

```bash
git checkout main
git pull --ff-only origin main
```

日常开发直接在 `main` 上进行。只有用户或团队明确要求隔离开发或代码评审时，才临时创建任务分支。

验证当前分支：

```bash
git branch
# 带 * 号的就是当前分支，默认应显示：* main
```

### 5. 搭建本地环境

```bash
# 按锁文件创建虚拟环境并安装 Python 依赖
uv sync --frozen

# 复制环境变量文件
copy .env.example .env
```

用记事本打开 `.env`，把 `OPENAI_API_KEY=sk-xxx` 里的 `sk-xxx` 换成真实的 API Key。

> `.env` 文件不会被提交到 git，每人只在自己电脑上保存。

---

## 二、日常开发流程

### 每次开始写代码前，先同步 main 的最新内容

```bash
git checkout main
git pull --ff-only origin main
```

### 写完代码后，提交到本地

```bash
# 第一步：查看改了哪些文件
git status

# 第二步：把要提交的文件加入暂存区（把 文件名 换成实际文件）
git add src/parser/word_parser.py
git add tests/test_parser.py

# 或者一次性添加所有改动（谨慎使用）
git add .

# 第三步：写提交信息并提交
git commit -m "feat: 实现 Word 文档条款级分块"
```

**提交信息格式说明：**

| 前缀 | 用途 | 示例 |
|---|---|---|
| `feat:` | 新功能 | `feat: 实现 PDF 解析链` |
| `fix:` | 修复 bug | `fix: 修复 Excel 多级表头识别` |
| `test:` | 增加测试 | `test: 添加 word_parser 单元测试` |
| `docs:` | 文档变更 | `docs: 更新接口说明` |

### 推送到 GitHub

```bash
git push origin main
```

推送后，去 GitHub 仓库页面可以看到你最新的提交。

---

## 三、可选的 Pull Request（PR）

默认直接在 `main` 开发和提交。只有用户或团队明确要求代码评审或隔离开发时，才创建临时分支并通过 PR 合入 `main`：

1. 从最新 `main` 创建临时分支，例如：`git checkout -b feature/parser-fix`

2. 完成开发和提交后，执行 `git push -u origin feature/parser-fix`

3. 打开浏览器，访问：https://github.com/wxl-0/trusted-rag-banking

4. 页面顶部会出现黄色提示条，点击 **"Compare & pull request"**

5. 填写 PR 信息：
   - 标题格式同 commit，例如：`feat: 完成 Word/PDF 解析模块`
   - 描述中说明：做了什么、怎么测试的、是否影响接口

6. 确认 **base 分支是 `main`**

7. 点击 **"Create pull request"**

8. 等待队长 Review，根据反馈修改后合并。

---

## 四、同步 main 的最新代码

开始开发或推送前，先同步远程 `main`：

```bash
git checkout main
git pull --ff-only origin main
```

如果 `--ff-only` 提示不能快进，先停止并确认本地、远程提交关系，不要直接执行强制覆盖。只有明确选择合并并出现冲突标记时，才打开对应文件处理 `<<<<<<<` 和 `>>>>>>>`，然后：

```bash
git add 冲突的文件名
git commit -m "fix: 解决与 main 的合并冲突"
```

---

## 五、常用命令速查

| 命令 | 作用 |
|---|---|
| `git status` | 查看哪些文件被修改了 |
| `git branch` | 查看当前在哪个分支 |
| `git pull` | 拉取远程最新代码 |
| `git add 文件名` | 把文件加入提交暂存区 |
| `git commit -m "说明"` | 提交到本地 |
| `git push` | 推送到 GitHub |
| `git log --oneline` | 查看提交历史 |
| `git diff` | 查看具体改了什么 |

---

## 六、注意事项

- 默认直接在最新 `main` 开发和提交；推送前确认暂存区和提交中没有无关文件
- **不要**提交 `.env` 文件（里面有 API Key）
- **不要**提交 `.venv/` 目录
- **不要**提交 `data/chunks/` 目录下的 JSONL 文件（共 40MB+，可本地重新生成）
- **不要**提交 `data/raw/` 和 `data/converted/` 目录（原始数据文件）
- 遇到不懂的报错，截图发给队长，不要随意执行不理解的命令

---

## 七、本地构建知识库（克隆后必做）

仓库不包含切块数据和向量索引，克隆后需要本地生成：

```bash
# 1. 确保 data/raw/ 下有原始文件（从共享网盘下载，不提交 git）

# 2. 解析文件 → 生成 chunk（输出到 data/chunks/）
uv run --frozen python scripts/ingest.py

# 3. 启动 Qdrant 并构建向量索引
docker compose up qdrant -d
uv run --frozen python scripts/build_index.py
```

如果队友更新了解析代码（parser/chunk_processor 等），拉取后需要重新执行上述步骤。

**重建索引前需清空旧数据**（chunk 内容变了，旧索引对不上）：

```bash
uv run --frozen python -c "from qdrant_client import QdrantClient; c=QdrantClient('localhost',port=6333); c.delete_collection('regulations'); c.delete_collection('tables')"
uv run --frozen python scripts/build_index.py
```

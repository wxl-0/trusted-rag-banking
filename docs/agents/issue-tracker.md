# Issue tracker: GitHub

本仓库的规格和开发任务使用 GitHub Issues 管理，所有操作在仓库目录中通过 `gh` CLI 完成，由当前 Git remote 自动确定目标仓库。

## 约定

- 创建 Issue：使用 `gh issue create`。
- 查看 Issue：使用 `gh issue view <number> --comments`，并同时读取标签。
- 列出 Issue：使用 `gh issue list`，按状态和标签筛选。
- 评论 Issue：使用 `gh issue comment <number>`。
- 修改标签：使用 `gh issue edit <number> --add-label` 或 `--remove-label`。
- 关闭 Issue：使用 `gh issue close <number>`，必要时附带说明。
- 当工程 Skill 要求“发布到 issue tracker”时，创建 GitHub Issue。
- `to-spec` 发布的规格使用 `ready-for-agent` 标签；标签不存在时先创建。

## Pull requests as a triage surface

**PRs as a request surface: no.**

Pull Request 不作为本仓库的需求或规格入口。GitHub 的 Issue 与 Pull Request 共用编号空间，遇到不明确的编号时，先尝试按 Pull Request 查询，再按 Issue 查询。

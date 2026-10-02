# Agent 工作入口

开始任务前先阅读 `README.md`，再按任务范围阅读 `docs/` 中对应文档。

- 产品行为与验收条件：`docs/requirements.md`
- 组件边界、数据模型与依赖方向：`docs/architecture.md`
- 开发、测试与交付门槛：`docs/workflow.md`
- 任务顺序与完成定义：`docs/plan.md`
- 固定编号的可验收故事：`docs/stories.md`

文档中的“待确认”项不是已批准的实现要求。实现时以已确认的验收条件为准；发现冲突时先更新相关文档和测试，再修改产品代码。保持前后端分离，后端领域逻辑不依赖 HTTP、队列和数据库框架。每项任务交付可复现的测试结果。

## Story coordination

This repository is developed by multiple Codex chats. Before changing a user story, inspect `docs/stories.md`, recent local commits, and the live claim directories under `$(git rev-parse --path-format=absolute --git-common-dir)/story-claims/`.

1. Claim exactly one story at a time with an atomic `mkdir` of `story-claims/US-NNN` in the Git common directory. If it already exists, another chat owns it; choose a different unclaimed story. Record the chat ID, branch, state, and start time in `OWNER.md` inside the claim directory. Never remove another chat's claim without explicit coordination.
2. Use a separate Git worktree and `codex/` branch for parallel implementation. Do not edit another chat's checkout or uncommitted files. Start from a local commit containing the dependencies of your story; wait for a dependency story to finish if necessary.
3. Run `make check` after code changes, then commit locally with the story ID in the commit message. Do not push, create or update a PR, or merge branches without user authorization. Keep generated OpenAPI and TypeScript schema in the same story commit as their API changes.
4. On completion, update your claim's state to `completed` with the commit ID. Keep the claim directory so another chat cannot accidentally implement the story again. Report the story ID, branch, commit, and verification result to the user. A failed or abandoned claim stays visible until the owner or user reassigns it.

Stories US-001 through US-009 are complete in local commits. Check live claims and recent commits for later stories. Independent stories can proceed in separate worktrees after claiming them.

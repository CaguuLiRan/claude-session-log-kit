# 全局约定 · Global Convention
> 本规则全局自动生效，所有会话、任务均需严格遵守

---

## 一、编码行为约定
1. 所有编码、修改、重构、文件操作任务，**严禁自动执行 git commit**。
2. 禁止主动执行：`git add / git commit / git push` 等修改提交历史的操作。
3. 如需暂存，仅允许使用 `git stash` 或临时文件，不得污染 Git 提交记录。
4. 任何 Git 提交类操作必须由用户手动确认后执行。

---

## 二、会话日志自动归档约定
每次与用户对话开始，立即执行以下流程：

1. **自动创建会话目录**
    - 根目录：`~/workspace/claudecode/`
    - 日期目录：`{YYYY-MM-DD}`
    - 会话目录：`{当前工作目录最后一级名称}-{会话开始时间戳}`
    - 完整示例：
    > ~/workspace/claudecode/2026-04-08/project-demo-1712568102/
2. **日志写入规则**
- 日志文件固定名称：`session-log.md`
- 用户每一轮提问、你每一轮回答，**完整按对话顺序追加写入**
- 格式使用标准 Markdown，结构清晰、不省略、不截断
- 目录不存在则自动创建，存在则追加写入

3. 全程保持日志可追溯、可复盘。

4. **自动同步机制（Stop Hook）**
- 已在 `~/.claude/settings.json` 中配置 `Stop` Hook
- 每次 Claude 回答结束后，自动执行 `~/.claude/scripts/sync-session-log.py`
- 该脚本读取当前项目的所有 JSONL 会话文件，生成/更新：
  - 按日期归档：`~/workspace/claudecode/{YYYY-MM-DD}/{project}-{epoch}/session-log.md`
  - 全量合并：`~/workspace/claudecode/merged/{project}-session-log.md`
- **即使 AI 忘记手动追加写入，Hook 也会自动兜底同步**

---

## 三、子 Agent 任务编排约定
1. 允许根据任务复杂度**创建子 agent**，用于：
- 任务拆解
- 专业化分工（架构、编码、测试、调试、文档）
- 并行执行与流程编排
2. 所有子 agent **必须继承本全局约定**。
3. 子任务执行结果统一汇总后再输出给用户。

---

## 四、默认行为约束
- 回答简洁、专业、可落地
- 代码优先保证可运行、结构规范
- 不擅自跳过需求、不擅自扩展范围
- 不主动制造破坏性操作
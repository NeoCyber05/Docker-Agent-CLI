# Agent Tools

LLM agent có thể gọi các tool sau trong phiên REPL. Tool được phân loại theo mức độ tác động; tool **destructive** hoặc **thay đổi runtime** yêu cầu user approve trước khi chạy.

---

## MCP runtime

Docker tool execution now goes through `docker-mcp-server` by default. The core agent loads namespaced MCP tools such as `docker.deploy_stack`, `docker.get_logs`, and `docker.destroy_stack`, while deterministic commands such as `destroy all stacks` are matched by the generic command router from plugin-provided metadata.

`docker.deploy_stack` is a two-phase operation: it returns a PendingAction for plan review, and `docker.confirm_action` runs the real apply-with-rollback transaction only after approval and revalidation.

---
## Bảng tổng quan

| Tool | Category | Mục đích |
| :--- Each record includes `createdAt`, `updatedAt`, `cwd`, `provider`, optional `model`, `firstPrompt`, `resources`, backward-compatible `stackNames`, and `messages[]`.
- `createdAt` is preserved across turns; only `updatedAt` changes when the record is saved again.
- `resources` stores generic `{server, type, name}` entries. Docker stacks are recorded as `{server: "docker", type: "stack", name: "..."}`; `stackNames` remains for old consumers.- Resume (`--resume` hoặc `/resume`) nạp lại transcript, **provider**, và `model` đã lưu. `/resume` mở danh sách phiên đã lưu để chọn. Dialog permission đang chờ **không** được resume.
- Nếu `cwd` lưu khác thư mục hiện tại, REPL và stderr hiển thị cảnh báo.
- Footer REPL hiển thị `session: <id>` đang active.

Chi tiết cấu trúc thư mục `.docker-agent`: xem [docker-agent-directory.md](./docker-agent-directory.md).

---

## Tài liệu liên quan

| Tài liệu | Nội dung |
| :--- | :--- |
| [DOCKER_API_MAPPING.md](./DOCKER_API_MAPPING.md) | Ánh xạ tool → hàm Python → Docker CLI / Engine API |
| [policies.md](./policies.md) | Policy YAML kiểm soát deploy |
| [docker-agent-directory.md](./docker-agent-directory.md) | Cấu trúc thư mục state, sessions, secrets |

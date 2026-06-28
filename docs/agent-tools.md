# Agent Tools

LLM agent có thể gọi các tool sau trong phiên REPL. Tool được phân loại theo mức độ tác động; tool **destructive** hoặc **thay đổi runtime** yêu cầu user approve trước khi chạy.

---

## Bảng tổng quan

| Tool | Category | Mục đích |
| :--- | :--- | :--- |
| `plan_stack` | high-level | Thiết kế stack và hiển thị plan preview |
| `apply_stack` | high-level | Apply plan đã được duyệt (chạy sau khi user confirm; **không** exposed trực tiếp cho LLM) |
| `stop_stack` | high-level | Dừng container của stack managed (`docker compose stop`), **không** xóa container |
| `destroy_stack` | high-level | Dừng và gỡ một stack (`docker compose down`) |
| `destroy_all_stacks` | high-level | Gỡ toàn bộ stack (yêu cầu gõ `DESTROY ALL`) |
| `remove_container` | high-level | Stop/remove container **orphan** (không thuộc stack managed); `stopOnly=true` để chỉ dừng |
| `list_stacks` | read-only | Liệt kê stack trong `docker-stacks/` |
| `get_stack_status` | read-only | Trạng thái container của stack |
| `get_logs` | read-only | Lấy log container |
| `get_health` | read-only | Trạng thái health-check runtime |
| `inspect_drift` | read-only | So sánh desired state vs running state |
| `remediate_drift` | high-level | Khắc phục drift về desired state |
| `pull_image` | escape-hatch | Validate và pre-pull Docker image |
| `exec_docker` | escape-hatch | Chạy lệnh `docker` chỉ đọc (`ps`, `inspect`, `logs`, …) |
| `validate_spec` | read-only | Preflight — kiểm tra spec trước deploy |
| `resolve_dependency` | read-only | Preflight — phân tích phụ thuộc service |
| `check_port_conflict` | read-only | Preflight — phát hiện xung đột cổng |

---

## `stop_stack` vs `destroy_stack` vs `remove_container`

| Nhu cầu | Tool |
| :--- | :--- |
| Tạm dừng stack/service managed, giữ YAML và container definition | `stop_stack` |
| Gỡ hẳn stack managed (compose down, archive state) | `destroy_stack` |
| Dọn container lẻ / orphan (không thuộc stack trong `docker-stacks/`) | `remove_container` |

Container thuộc stack managed **không** dùng được `remove_container` — agent sẽ bị chặn và gợi ý `stop_stack` hoặc `destroy_stack`.

Khởi động lại sau `stop_stack`: gọi `apply_stack` (hoặc nhờ agent deploy lại stack).

---

## Phê duyệt và quyền

Các tool sau **bắt buộc** user approve trong REPL:

| Tool | Ghi chú |
| :--- | :--- |
| `apply_stack` | Sau khi user duyệt plan |
| `stop_stack` | Dừng container, không xóa |
| `destroy_stack` | `removeVolumes: true` yêu cầu typed confirm `DESTROY <stack>` |
| `destroy_all_stacks` | Yêu cầu typed confirm `DESTROY ALL` |
| `remove_container` | ≥3 container yêu cầu typed confirm `REMOVE N CONTAINERS` |
| `remediate_drift`, `pull_image`, `exec_docker` | Theo policy permission gate |

- Flag `--yes` chỉ auto-approve permission **non-destructive**; các tool trên vẫn bị gate.
- `plan_stack` và `remediate_drift` chạy qua [policy engine](./policies.md) trước khi user thấy plan preview.

---

## Session persistence

- Transcript lưu tại `.docker-agent/sessions/<id>.json` sau mỗi turn (secrets đã redact).
- Mỗi bản ghi gồm `createdAt`, `updatedAt`, `cwd`, `provider`, `model` (tùy chọn), `firstPrompt`, `stackNames`, và mảng `messages[]`.
- `createdAt` giữ nguyên qua các turn; chỉ `updatedAt` thay đổi khi lưu lại.
- `stackNames` lấy từ stack đang quản lý trong `docker-stacks/`.
- Resume (`--resume` hoặc `/resume`) nạp lại transcript, **provider**, và `model` đã lưu. `/resume` mở danh sách phiên đã lưu để chọn. Dialog permission đang chờ **không** được resume.
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

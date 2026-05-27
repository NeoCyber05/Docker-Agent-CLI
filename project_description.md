## 1. Mô tả bài toán

Xây dựng hệ thống cho phép người dùng quản lý hạ tầng thông qua lệnh ngôn ngữ tự nhiên. Hệ thống sử dụng AI Agent với kiến trúc ReAct (Reasoning + Acting) để phân tích yêu cầu, lập kế hoạch thực thi, và triển khai hạ tầng tự động.

## 2. Kiến trúc hệ thống

- AI Agent Core: Nhận lệnh ngôn ngữ tự nhiên, sử dụng LLM (Gemini/OpenAI/Ollama) để suy luận và lập kế hoạch hành động.
- Tool System: Tập hợp các công cụ (tools) mà Agent có thể gọi: tạo container, cấu hình network, quản lý volume, kiểm tra trạng thái.
- State Manager: Theo dõi trạng thái hạ tầng hiện tại (desired state vs actual state), phát hiện configuration drift.
- Execution Engine: Thực thi kế hoạch theo đúng thứ tự dependency, hỗ trợ dry-run để xem trước thay đổi.

## 3. Yêu cầu chức năng

Giai đoạn 1 (Mini Project — CLI):

- Xây dựng CLI tool cho phép người dùng nhập lệnh bằng ngôn ngữ tự nhiên
- Ví dụ: "Tạo một web application gồm nginx reverse proxy, 2 instance node.js backend, và 1 postgresql database"
- Agent phân tích yêu cầu → tạo execution plan → hiển thị cho người dùng xác nhận
- Chế độ dry-run: hiển thị chi tiết những gì sẽ được tạo mà không thực thi
- Sau khi xác nhận: tự động sinh Docker Compose YAML và triển khai
- Quản lý state: lưu trạng thái hạ tầng, hỗ trợ lệnh "show status", "destroy all"
- Phát hiện drift: so sánh desired state với actual state của Docker containers

## 4. Yêu cầu kỹ thuật

- Backend: Node.js (TypeScript)
- AI Integration: Tích hợp ít nhất 1 LLM provider
- Container Runtime: Docker Engine API hoặc Docker Compose CLI
- Design Pattern: ReAct Agent pattern (Reason → Act → Observe → Repeat)
- State Storage: File-based (JSON/YAML) hoặc SQLite
# ROLE & OBJECTIVE

Bạn là một **Principal Frontend Architect (React/TypeScript)** và **Senior Python FastAPI Engineer**.
Nhiệm vụ của bạn là thiết kế và viết mã nguồn hoàn chỉnh (production-ready) cho phân hệ **Web Frontend** (kèm một số API `GET` đọc danh mục bổ trợ ở Backend) của hệ thống **Enterprise RAG & Tabular Execution Harness (Trợ lý AI Hỏi đáp Đa phương thức Nội bộ Doanh nghiệp)**.

Hệ thống vận hành **100% OFFLINE trong mạng LAN nội bộ (Air-gapped)**, không sử dụng Docker, không gọi bất kỳ CDN bên ngoài nào (không dùng Google Fonts CDN, unpkg, jsdelivr...). Toàn bộ thư viện, icon, font chữ phải được đóng gói cục bộ trong `node_modules` và bundle qua Vite.

---

# 1. BỐI CẢNH HỆ THỐNG BACKEND HIỆN TẠI (EXISTING BACKEND CONTRACT)

Backend được viết bằng **FastAPI + SQLAlchemy 2.0 (PostgreSQL 16) + Qdrant + DuckDB/Pandas Sandbox**, nằm tại thư mục gốc của dự án (`api/`, `application/`, `infrastructure/`, `domain/`, `config.py`).

### 1.1. Cơ chế Xác thực & Phân quyền (Reverse-Proxy ADSSO)
- Người dùng được xác thực tự động bởi tầng Reverse Proxy (Nginx/IIS ADSSO) phía trước.
- Reverse Proxy tự động đính kèm các HTTP Header vào mọi request gửi tới Backend:
  - `X-User-Id`: Mã nhân viên (VD: `nv_001`)
  - `X-Department-Id`: Mã phòng ban (VD: `FINANCE`, `HR`, `IT`, `SALES`)
  - `X-User-Role`: Vai trò (`user`, `analyst`, `admin`)
  - `X-User-Name`: Họ và tên hiển thị (VD: `Nguyễn Văn A`)
- **Yêu cầu nghiêm ngặt trên Frontend:**
  - **TUYỆT ĐỐI KHÔNG** hiển thị bộ chuyển đổi (Switcher) chọn User/Phòng ban/Role giả lập hay màn hình nhập tay `X-User-Id`.
  - Frontend tự động lấy thông tin định danh của người dùng hiện tại từ Backend qua API `GET /me` và chỉ hiển thị ở dạng **Read-only Profile Badge** (Họ tên, Phòng ban, Vai trò) trên thanh Sidebar/Header.

### 1.2. Các API Backend Đã Có Sẵn
1. **`POST /upload`** (`multipart/form-data`):
   - Input: `file` (`.xlsx`, `.csv`, `.pdf`, `.docx`, `.md`, `.txt`, tối đa 30MB), `is_public` (`bool`, mặc định `false`).
   - Output (`202 Accepted` hoặc `200 OK` nếu trùng SHA-256):
     ```json
     {
       "status": "PENDING" | "DUPLICATE",
       "job_id": "uuid",
       "file_id": "uuid",
       "job_type": "TABULAR" | "DOCUMENT",
       "message": "..."
     }
     ```
2. **`GET /upload/{job_id}`**:
   - Output:
     ```json
     {
       "job_id": "uuid",
       "file_id": "uuid",
       "job_type": "TABULAR" | "DOCUMENT",
       "status": "PENDING" | "PROCESSING" | "SUCCESS" | "FAILED",
       "progress_pct": 60,
       "error_message": null,
       "created_at": "2026-10-26T...",
       "finished_at": "2026-10-26T..."
     }
     ```
3. **`DELETE /files/{file_id}`**:
   - Xóa file gốc, file `.parquet`, các điểm vector trong Qdrant và bản ghi PostgreSQL (chỉ chủ sở hữu hoặc Admin mới được xóa).
4. **`POST /chat`**:
   - Input:
     ```json
     {
       "message": "Doanh thu quý 1 của chi nhánh Hà Nội là bao nhiêu?",
       "session_id": "optional-uuid",
       "is_public_only": false
     }
     ```
   - Output (`ChatApiResponse`):
     ```json
     {
       "session_id": "uuid",
       "message_id": "uuid",
       "answer_markdown": "Nội dung câu trả lời định dạng Markdown (chứa bảng Markdown, nhận xét, trích dẫn [1], [2] và mục 📚 Chỉ mục nguồn trích dẫn)...",
       "route": "TABULAR" | "DOCUMENT" | "HYBRID" | "CLARIFY" | "CHITCHAT" | "OUT_OF_SCOPE",
       "sources": [
         {
           "index": 1,
           "file_name": "Quy_che_tai_chinh.pdf",
           "page": 4,
           "section_title": "Điều 5. Mức thưởng",
           "quote": "Trích đoạn nguyên văn...",
           "score": 0.892
         }
       ],
       "tables": [
         {
           "table_name": "BaoCao.xlsx - DoanhThu",
           "file_name": "BaoCao.xlsx",
           "sheet_name": "DoanhThu",
           "total_rows": 120,
           "displayed_rows": 20,
           "columns": ["ma_sp", "ten_sp", "doanh_thu"]
         }
       ],
       "debug": {
         "rewritten_query": "Doanh thu quý 1 năm 2026 của chi nhánh Hà Nội là bao nhiêu?",
         "language": "sql",
         "code": "SELECT ... FROM \"DoanhThu\" WHERE ...",
         "attempts": 1,
         "latency_ms": 1420.5,
         "rerank_scores": [0.892, 0.741]
       }
     }
     ```
   *(Lưu ý: Trường `debug` chỉ khác `null` khi người dùng có role `admin`).*
5. **`POST /feedback`**:
   - Input:
     ```json
     {
       "message_id": "uuid",
       "feedback_type": "thumbs_up" | "thumbs_down",
       "comment": "Nhận xét tùy chọn",
       "suggested_sql": "SELECT ... (tùy chọn sửa lại SQL đúng để promote thành verified few-shot)"
     }
     ```
6. **`GET /health`**:
   - Output: `{"status": "healthy" | "degraded" | "unhealthy", "database": "connected", "vector_store": "ready", "app_env": "production", "timezone": "Asia/Ho_Chi_Minh"}`.

---

# 2. YÊU CẦU MỞ RỘNG BACKEND (LIGHTWEIGHT READ APIs & STATIC SERVING)

Hãy bổ sung các endpoint đọc dữ liệu sau vào Backend FastAPI (tuân thủ chặt chẽ kiến trúc hiện có và kiểm tra quyền RBAC bằng `get_current_user` trong `api/dependencies/auth.py`):

1. **`GET /me`** (trong `api/routes/auth.py` hoặc `api/main.py`):
   - Trả về thông tin người dùng hiện tại từ `AuthContext` (đọc từ Reverse Proxy headers):
     ```json
     {
       "user_id": "...",
       "full_name": "...",
       "department_id": "...",
       "role": "...",
       "is_admin": false
     }
     ```
2. **`GET /files`** (bổ sung vào `api/routes/upload.py`):
   - Liệt kê các tệp trong `FileModel` mà người dùng hiện tại có quyền xem:
     - Nếu `auth.is_admin`: thấy toàn bộ tệp (hỗ trợ query param tùy chọn `department_id`, `is_public_only`).
     - Nếu user thường: chỉ thấy tệp có `department_id == auth.department_id` HOẶC `is_public == True` HOẶC `owner_user_id == auth.user_id`.
   - Với mỗi tệp, trả về kèm trạng thái `IngestionJobModel` mới nhất (`status`, `progress_pct`, `error_message`), thông tin tóm tắt bảng (`tables_catalog`: danh sách `sheet_name`, `row_count`, `table_description`) hoặc tài liệu (`documents`: `total_pages`, `total_chunks`), và cờ `can_delete: bool` (`auth.is_admin or file.owner_user_id == auth.user_id`).
3. **`GET /sessions`**, **`GET /sessions/{session_id}/messages`**, và **`DELETE /sessions/{session_id}`** (bổ sung vào `api/routes/chat.py`):
   - `GET /sessions`: Trả về danh sách phiên hội thoại (`ChatSessionModel`) của `auth.user_id`, sắp xếp theo `updated_at DESC` (`id`, `title`, `created_at`, `updated_at`).
   - `GET /sessions/{session_id}/messages`: Kiểm tra phiên hội thoại thuộc về `auth.user_id` (hoặc `auth.is_admin`, nếu không trả về `403`). Trả về danh sách `ChatMessageModel` theo thứ tự `created_at ASC`. Với tin nhắn `assistant`, giải nén `structured_response` (`route`, `sources`, `tables`, và chỉ trả về `debug` nếu `auth.is_admin == True`, kèm `feedback` đã đánh giá).
   - `DELETE /sessions/{session_id}`: Cho phép chủ sở hữu phiên chat (hoặc Admin) xóa cuộc trò chuyện.
4. **Phục vụ Static Frontend trực tiếp từ FastAPI (Zero-Docker Deployment):**
   - Trong `api/main.py`, nếu thư mục `frontend/dist` tồn tại (sau khi chạy `npm run build`), tự động mount static assets (`/assets`) và phục vụ `index.html` cho SPA fallback để hệ thống có thể chạy chỉ bằng 1 tiến trình `uvicorn` duy nhất trong mạng LAN (bên cạnh chế độ chạy dev server Vite qua proxy).

---

# 3. KIẾN TRÚC & TÍNH NĂNG CHI TIẾT CỦA FRONTEND (`frontend/`)

## 3.1. Công nghệ bắt buộc (Tech Stack)
- **Core:** React 18 + TypeScript + Vite.
- **Styling & UI Components:** Tailwind CSS + các component theo chuẩn **shadcn/ui** (Radix UI primitives / Lucide React icons).
- **Quản lý trạng thái & Gọi API:** `@tanstack/react-query` (hoặc custom hooks chuẩn xác có quản lý cache/polling) + `axios` / `fetch` client.
- **Hiển thị Markdown & Toán/Bảng:** `react-markdown` + `remark-gfm` (hỗ trợ GitHub Flavored Markdown tables, code blocks, lists).
- **Biểu đồ trực quan:** `recharts` (đóng gói local trong `node_modules`).
- **Xuất dữ liệu bảng:** Xuất bảng dữ liệu trên giao diện ra file `.csv` (UTF-8 with BOM `\uFEFF` để mở bằng Excel tiếng Việt không bị lỗi font) hoặc `.xlsx` hoàn toàn ở phía Client.
- **100% Offline-first:** Không nhúng bất kỳ link `<link href="https://fonts.googleapis.com...">` hay script ngoài internet nào trong `index.html`. Sử dụng system font stack tối ưu cho tiếng Việt (`Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`) và `"JetBrains Mono", Consolas, monospace` cho SQL/Code.

## 3.2. Bố cục Giao diện (Enterprise Dashboard Layout & Light/Dark Mode)
Thiết kế giao diện hiện đại, tinh tế, hỗ trợ chuyển đổi mượt mà **Sáng / Tối (Light / Dark Mode)** (lưu trạng thái vào `localStorage` và tôn trọng `prefers-color-scheme`):

1. **Thanh bên trái (Collapsible Left Sidebar - 280px):**
   - **Logo & Trạng thái hệ thống:** Tên hệ thống + chấm tròn trạng thái kết nối thời gian thực từ `GET /health` (`Healthy` xanh lá / `Degraded` vàng / `Unhealthy` đỏ).
   - **Nút "Cuộc trò chuyện mới" (`+ New Chat`):** Khởi tạo phiên hỏi đáp mới.
   - **Chuyển đổi 2 Tab chính hoặc 2 phân vùng trên Sidebar:**
     - **Lịch sử Hội thoại (Chat Sessions):** Danh sách các phiên chat từ `GET /sessions`, nhóm theo thời gian (Hôm nay, 7 ngày qua, Cũ hơn), có nút xóa phiên chat kèm xác nhận.
     - **Kho Tri thức & Dữ liệu (Knowledge & Data Vault):** Mở ngăn quản lý/xem danh sách các file `.xlsx`, `.csv`, `.pdf`, `.docx`, `.md`, `.txt` mà phòng ban được phép truy cập.
   - **Footer Thông tin Người dùng (Read-only SSO Profile):**
     - Hiển thị Avatar viết tắt, `full_name`, badge `department_id` và badge `role` (`ADMIN` nổi bật nếu `is_admin == true`).
     - Nút chuyển đổi giao diện Sáng / Tối (Sun/Moon toggle).

2. **Không gian làm việc chính (Main Workspace):**
   - **Header ngữ cảnh:**
     - Tiêu đề phiên hội thoại hiện tại.
     - Công tắc bật/tắt **"Chỉ tìm dữ liệu công khai" (`is_public_only`)**: Khi bật, mọi truy vấn chỉ tìm trên các tài liệu/bảng chung của toàn công ty.
     - Nút mở nhanh **Kho Dữ liệu / Upload File** (Drawer hoặc Modal).
   - **Khung Hội thoại (Chat Stream):**
     - Khi chưa có tin nhắn (Empty State): Hiển thị màn hình chào mừng trang trọng kèm **4–6 thẻ gợi ý câu hỏi mẫu (Starter Prompts)** phân loại theo 3 nhóm: *Tra cứu số liệu bảng (`TABULAR`)*, *Tra cứu văn bản quy chế (`DOCUMENT`)*, và *Truy vấn kết hợp (`HYBRID`)* dựa trên chính tên các bảng/tài liệu hiện có trong phòng ban của user!
     - Khi đang chờ phản hồi: Hiệu ứng Skeleton / Stepper trạng thái thông minh (*"Đang phân tích ý định & phân quyền RBAC..." $\rightarrow$ "Đang truy vấn dữ liệu & kiểm tra trích dẫn..."*).

## 3.3. Bốn Tính Năng Trải Nghiệm Chuyên Biệt (Signature UX Features)

### Tính năng 1: Interactive Citations `[1]`, `[2]` & Source Inspector Drawer
- Trong nội dung câu trả lời của trợ lý (`answer_markdown`), tự động nhận diện các ký hiệu trích dẫn `[1]`, `[2]`, `[3]`... và biến chúng thành các **Citation Pill / Badge tương tác** (màu xanh nổi bật, có hiệu ứng hover).
- **Khi rê chuột (Hover) vào `[n]`:** Hiển thị ngay một Popover nhỏ gọn gồm:
  - Tên tệp nguồn (`file_name`) + Số trang (`Trang X`) + Mục (`section_title`).
  - Điểm độ tin cậy Reranker (`score`, hiển thị dạng phần trăm hoặc thanh tiến trình).
  - Đoạn trích dẫn nguyên văn (`quote`) đặt trong khung trích dẫn.
- **Khi nhấp chuột (Click) vào `[n]`:** Mở **Source Inspector Drawer** bên phải màn hình, làm nổi bật (highlight) thẻ nguồn số `[n]` trong danh sách toàn bộ nguồn tham khảo của câu trả lời đó để người dùng đối chiếu nhanh.

### Tính năng 2: Smart Data Table & Quick Chart (Trực quan hóa Bảng số liệu)
- Đối với các câu trả lời thuộc nhánh `TABULAR` hoặc `HYBRID` có chứa bảng Markdown trong `answer_markdown`:
  - Tự động parse bảng Markdown từ câu trả lời (kết hợp metadata từ trường `tables: TableResultDTO[]`) để nâng cấp thành **Smart Data Table Component** có thanh công cụ phía trên bảng:
    1. **Chuyển đổi chế độ xem (Tabs):** `📋 Bảng dữ liệu` | `📈 Biểu đồ trực quan`.
    2. **Tìm kiếm & Sắp xếp tại chỗ:** Ô lọc nhanh các dòng trong bảng + click vào tiêu đề cột để sắp xếp Tăng/Giảm (xử lý đúng kiểu số định dạng Việt Nam `1.234.567,89` và ngày tháng `dd/mm/yyyy`).
    3. **Xuất dữ liệu (Export):** Nút **"Tải CSV"** (UTF-8 BOM) và **"Sao chép bảng"** chỉ với 1 cú click.
    4. **Quick Chart (`recharts`):** Nếu bảng có ít nhất 1 cột chuỗi/thời gian (trục X) và 1 cột số (trục Y, từ 2 đến 50 dòng), cho phép người dùng chuyển sang tab **Biểu đồ** để xem ngay **Bar Chart / Line Chart / Pie Chart** (có thể chọn cột trục X, cột trục Y và loại biểu đồ).
  - Hiển thị rõ huy hiệu nguồn dữ liệu ở chân bảng: `📊 Nguồn: [file_name] — Sheet: [sheet_name] (Hiển thị X / Y dòng)`.

### Tính năng 3: Admin Diagnostics Panel & Few-Shot SQL Curation (Feedback Loop)
- **Badge Định tuyến (Route Badge):** Ở đầu mỗi câu trả lời của trợ lý, hiển thị badge trực quan cho biết nhánh thực thi:
  - `📊 Dữ liệu Bảng (TABULAR)`
  - `📄 Tài liệu Văn bản (DOCUMENT)`
  - `⚡ Kết hợp Đa nguồn (HYBRID)`
  - `❓ Cần làm rõ (CLARIFY)`
  - `💬 Giao tiếp (CHITCHAT)` / `🚫 Ngoài phạm vi (OUT_OF_SCOPE)`
- **Admin Diagnostics Accordion (Chỉ hiển thị khi `debug != null`, tức `is_admin == true`):**
  - Một khung kỹ thuật có thể đóng/mở ngay dưới câu trả lời, hiển thị:
    - **Câu hỏi đã viết lại (`rewritten_query`)**
    - **Ngôn ngữ thực thi (`language`: DuckDB SQL / Python Pandas)** & **Số lần thử (`attempts`)**
    - **Thời gian xử lý (`latency_ms` ms)** & **Điểm Reranker (`rerank_scores`)**
    - **Khối mã lệnh (`code`):** Hiển thị câu lệnh SQL hoặc code Python với nút Copy và định dạng rõ ràng.
- **Hệ thống Đánh giá (👍 / 👎) & Chỉnh sửa SQL (`POST /feedback`):**
  - Dưới mỗi tin nhắn của trợ lý có nút 👍 (**Hữu ích**) và 👎 (**Chưa chính xác**).
  - Khi bấm 👍 trên một câu trả lời `TABULAR` / `HYBRID`:
    - Có thể gửi ngay phản hồi tích cực (để Backend tự động lưu câu SQL hiện tại vào `fewshot_examples` với `source='verified'`), HOẶC bấm nút **"🔧 Chỉnh sửa & Xác nhận SQL mẫu"** mở Modal cho phép kiểm tra/chỉnh sửa lại câu lệnh `suggested_sql` và ghi chú `comment` trước khi lưu vào bộ nhớ Few-Shot của hệ thống.
  - Khi bấm 👎: Mở popover/modal nhỏ cho phép nhập lý do lỗi (`comment`) và (nếu muốn) nhập câu lệnh `suggested_sql` chuẩn xác để dạy lại hệ thống.

### Tính năng 4: Trình Quản lý File Upload & Theo dõi Tiến trình Thời gian thực (Ingestion Tracker)
- Hỗ trợ kéo-thả (Drag & Drop) tệp `.xlsx`, `.csv`, `.pdf`, `.docx`, `.md`, `.txt` (kiểm tra định dạng và dung lượng $\le 30\text{MB}$ ngay tại Client trước khi gửi).
- Tùy chọn công tắc **"Chia sẻ công khai cho toàn công ty (`is_public`)"** hoặc **"Chỉ nội bộ phòng ban hiện tại"** trước khi bấm tải lên.
- Sau khi gọi `POST /upload` nhận về `job_id` với trạng thái `PENDING`:
  - Tự động **polling `GET /upload/{job_id}` mỗi 1.5 giây** cho đến khi `status` chuyển sang `SUCCESS` hoặc `FAILED`.
  - Hiển thị thanh tiến trình (`progress_pct` từ 0% $\rightarrow$ 20% $\rightarrow$ 60% $\rightarrow$ 100%) kèm mô tả giai đoạn tương ứng (ví dụ: *"Đang làm sạch ô gộp & chuyển đổi Parquet..."*, *"Đang sinh mô tả bảng & kiểm tra Few-Shot SQL trong DuckDB..."*, hoặc *"Đang bóc tách cấu trúc văn bản & nhúng BGE-M3 vào Qdrant..."*).
- Trong danh sách tệp (`GET /files`), hiển thị chi tiết từng tệp:
  - Loại tệp (Icon Excel / CSV / PDF / Word / Markdown).
  - Phạm vi quyền (`Công khai` hoặc `Phòng ban: <department_id>`).
  - Danh sách các Sheet kèm số dòng & mô tả tự động (đối với file bảng) hoặc số trang & số đoạn trích (đối với file văn bản).
  - Nút **Xóa tệp (`DELETE /files/{file_id}`)** (chỉ hiển thị khi `can_delete == true`) có hộp thoại xác nhận tránh xóa nhầm.

---

# 4. YÊU CẦU BÀN GIAO (DELIVERABLES)

Hãy thực hiện tuần tự và đầy đủ các bước sau (viết code hoàn chỉnh, tuyệt đối không dùng `TODO`, `pass` hay rút gọn `...`):

1. **Bước 1 — Bổ sung các API Đọc & Static Serving cho Backend:**
   - Cập nhật `api/routes/upload.py` (`GET /files`).
   - Cập nhật `api/routes/chat.py` (`GET /sessions`, `GET /sessions/{session_id}/messages`, `DELETE /sessions/{session_id}`).
   - Cập nhật `api/main.py` (`GET /me` và cấu hình phục vụ thư mục `frontend/dist` nếu tồn tại).
   - Viết bổ sung các bài kiểm thử trong `tests/test_api.py` cho `GET /me`, `GET /files`, `GET /sessions`, `GET /sessions/{id}/messages`, `DELETE /sessions/{id}` và chạy `python -m pytest` để đảm bảo 100% test đều PASS.
2. **Bước 2 — Khởi tạo & Xây dựng toàn bộ mã nguồn Frontend trong thư mục `frontend/`:**
   - Cấu hình `package.json`, `vite.config.ts` (cấu hình proxy `/upload`, `/files`, `/chat`, `/sessions`, `/feedback`, `/health`, `/me` sang `http://127.0.0.1:8000` khi chạy dev), `tsconfig.json`, `tailwind.config.js`, `postcss.config.js`, `index.html`.
   - Tổ chức kiến trúc thư mục `frontend/src/` sạch sẽ, tách biệt rõ ràng:
     - `src/types/api.ts`: Định nghĩa đầy đủ TypeScript interfaces khớp 100% với DTO của Backend.
     - `src/services/apiClient.ts`: Tầng giao tiếp HTTP có xử lý lỗi tập trung.
     - `src/components/layout/`: `Sidebar.tsx`, `Header.tsx`, `ThemeToggle.tsx`, `HealthBadge.tsx`.
     - `src/components/chat/`: `ChatContainer.tsx`, `MessageBubble.tsx`, `CitationBadge.tsx`, `SourceInspectorDrawer.tsx`, `SmartTableRenderer.tsx`, `QuickChartView.tsx`, `AdminDiagnosticsPanel.tsx`, `FeedbackModal.tsx`.
     - `src/components/files/`: `FileVaultDrawer.tsx`, `FileUploadDropzone.tsx`, `IngestionJobTracker.tsx`.
3. **Bước 3 — Kiểm tra Build & Hướng dẫn Vận hành Offline:**
   - Kiểm tra TypeScript typecheck và chạy thử `npm run build` (nếu môi trường có Node.js) để đảm bảo không có bất kỳ lỗi biên dịch nào.
   - Cung cấp hướng dẫn đóng gói `node_modules` / `frontend/dist` và lệnh khởi chạy hệ thống trên máy chủ LAN Offline (Windows/Linux) không cần Docker.

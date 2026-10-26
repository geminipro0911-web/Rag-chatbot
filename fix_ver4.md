# Báo Cáo Review Hệ Thống Mbot — Phiên Bản 4 (`fix_ver4.md`)
**Phạm vi kiểm tra:** Toàn bộ mã nguồn Frontend (`d:\Project\RAG_chatbot\frontend\`) và phần mở rộng Backend Read APIs (`api/main.py`, `api/routes/chat.py`, `api/routes/upload.py`, `tests/test_api.py`).

## Tổng quan kiểm thử hiện tại
- **Frontend Build (`tsc && vite build`):** Thành công (`0 errors`).
- **Backend Test Suite (`pytest`):** Đạt **73/73 tests PASSED**.
- **Các lỗi phát hiện cần khắc phục:** **7 lỗi** (2 lỗi mức **HIGH**, 4 lỗi mức **MEDIUM**, 1 lỗi mức **LOW**).

---

## 🔴 LỖI 1 [HIGH]: Ô nhiễm Cache React Query (`['session-messages', null]`) làm hỏng nút "+ Cuộc trò chuyện mới" và nuốt lỗi khi gửi tin nhắn đầu tiên

### Vị trí
- `frontend/src/App.tsx` (dòng 39–106)
- `frontend/src/components/chat/ChatContainer.tsx`

### Nguyên nhân
1. Khi người dùng đang ở màn hình cuộc trò chuyện mới (`activeSessionId === null`), hàm `handleSendMessage` (dòng 66) ghi `optimisticUserMsg` vào khóa cache `['session-messages', null]` thông qua:
   ```ts
   qc.setQueryData<ChatMessageItemDTO[]>(['session-messages', activeSessionId], (old = []) => [
     ...old,
     optimisticUserMsg,
   ]);
   ```
2. Khi `apiClient.sendChatMessage` trả về `res.session_id` mới (dòng 78–79), ứng dụng gọi `setActiveSessionId(res.session_id)` nhưng **không xóa dữ liệu tạm trong `['session-messages', null]`**.
3. Do `useQuery` tại dòng 39–44 đặt `enabled: !!activeSessionId` (`false` khi `activeSessionId === null`), nên khi người dùng nhấn nút **"+ Cuộc trò chuyện mới"** (`handleNewChat` đặt `setActiveSessionId(null)`), React Query không fetch lại mà trả về mảng `[optimisticUserMsg]` cũ còn lưu trong cache `['session-messages', null]`. Hệ quả là người dùng **không thể quay về màn hình chào mừng (`WelcomeStarterPrompts`)** mà luôn thấy tin nhắn cũ bị kẹt trên màn hình.
4. Ngoài ra, trong khối `catch (err)` (dòng 85–90): nếu gửi tin nhắn ở phiên mới (`activeSessionId === null`) gặp lỗi mạng hoặc HTTP 500, lệnh `if (activeSessionId) await refetchMessages()` không chạy và cũng không xóa `['session-messages', null]`, khiến tin nhắn lỗi bị treo trên màn hình và không có thông báo lỗi nào hiển thị cho người dùng.

### Cách khắc phục yêu cầu
1. Trong `frontend/src/App.tsx`:
   - Bổ sung state `chatError: string | null` để lưu thông báo lỗi nếu gửi tin nhắn thất bại.
   - Khi nhận phản hồi thành công từ `apiClient.sendChatMessage` lúc `!activeSessionId`:
     - Xóa sạch cache `['session-messages', null]` bằng `qc.setQueryData(['session-messages', null], [])` (hoặc `qc.removeQueries({ queryKey: ['session-messages', null] })`).
     - Đặt trước dữ liệu cho session mới (`qc.setQueryData(['session-messages', res.session_id], ...)`) trước hoặc cùng lúc với `setActiveSessionId(res.session_id)`.
   - Trong khối `catch (err)`:
     - Nếu `!activeSessionId`, xóa `qc.setQueryData(['session-messages', null], [])`.
     - Nếu có `activeSessionId`, gọi `await refetchMessages()`.
     - Cập nhật `setChatError(err.message || 'Không thể gửi tin nhắn. Vui lòng thử lại.')`.
   - Trong `handleNewChat()`:
     - Gọi `qc.setQueryData(['session-messages', null], [])` và `setChatError(null)` cùng với `setActiveSessionId(null)`.
2. Truyền `chatError` và `onDismissError={() => setChatError(null)}` xuống `ChatContainer.tsx` để hiển thị banner cảnh báo lỗi rõ ràng phía trên ô nhập liệu khi có lỗi xảy ra.

---

## 🔴 LỖI 2 [HIGH]: Dùng `parseFloat` nhận diện nhầm Ngày tháng (`dd/mm/yyyy`) và Mã định danh bắt đầu bằng số thành kiểu Số trong Bảng & Biểu đồ

### Vị trí
- `frontend/src/components/chat/QuickChartView.tsx` (dòng 35–56, 75–81)
- `frontend/src/components/chat/SmartTableRenderer.tsx` (dòng 67–84)
- `frontend/src/utils/formatters.ts` (dòng 40–53)

### Nguyên nhân
1. Trong JavaScript, `parseFloat("15/03/2026")` hoặc `parseFloat("2026-Q1")` hay `parseFloat("101_SP")` chỉ đọc các chữ số đầu và bỏ qua phần ký tự phía sau, trả về `15`, `2026`, `101` (`!isNaN(...) === true`).
2. **Tại `QuickChartView.tsx` (dòng 35–42):**
   - Hàm `cleanNumber` dùng `parseFloat(s)` khiến mọi cột ngày tháng (`15/03/2026`, `2026-03-15`) hoặc mã định danh/quý bắt đầu bằng chữ số (`2026-Q1`, `12 Tháng`) đều bị phân loại nhầm vào **`numericCols` (Trục Y)** với giá trị bị cắt cụt (`15`, `2026`) thay vì **`categoryCols` (Trục X)**.
   - Thêm vào đó, `xAxisCol` và `yAxisCol` (dòng 75–81) chỉ khởi tạo một lần trong `useState(() => ...)` mà không đồng bộ lại nếu `columnAnalysis` thay đổi hoặc khi cột X và cột Y trùng nhau.
3. **Tại `SmartTableRenderer.tsx` (dòng 67–84):**
   - Khi sắp xếp cột (`handleSort`), các giá trị ngày `dd/mm/yyyy` (VD: `15/03/2026` và `02/11/2026`) đều thỏa mãn `!isNaN(numA) && !isNaN(numB)` (vì `parseFloat` trả về `15` và `2`), dẫn đến bảng **chỉ sắp xếp theo ngày (`dd`)** chứ không sắp xếp theo `yyyy-mm-dd`!
   - Ngay cả khi xuống nhánh `Date` (dòng 78), `new Date("15/03/2026")` trong JS chuẩn trả về `Invalid Date` vì JS mặc định parse `mm/dd/yyyy`.
4. **Tại `formatters.ts` (`formatViNumber`, dòng 40–53):**
   - Các mã có chữ số `0` đứng đầu (VD: mã nhân viên `"00125"`, số điện thoại) bị regex `/^-?\d+(\.\d+)?$/` coi là số và biến thành `"125"`.

### Cách khắc phục yêu cầu
1. Viết hàm tiện ích parse số chuẩn xác (toàn chuỗi) trong `frontend/src/utils/formatters.ts` (ví dụ `parseStrictNumber(val: string | number | null | undefined): number | null`):
   - Không coi các chuỗi có số `0` đứng đầu nhiều chữ số (như `"0123"`) hoặc chuỗi chứa `/`, `-` (ở giữa), chữ cái là số.
   - Hỗ trợ chuẩn số tiếng Việt (`1.234.567,89` -> `1234567.89`) và chuẩn số quốc tế (`1234567.89`), kiểm tra toàn chuỗi khớp `/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/` sau khi chuẩn hóa dấu phân cách, rồi mới dùng `Number(clean)`.
2. Viết hàm tiện ích parse ngày tiếng Việt `parseViDateTimestamp(val: string): number | null` hỗ trợ cả `dd/mm/yyyy` (VD: `15/03/2026`) và ISO `yyyy-mm-dd`.
3. Sử dụng `parseStrictNumber` trong `QuickChartView.tsx`, `SmartTableRenderer.tsx` và `formatViNumber` (`formatters.ts`), đồng thời dùng `parseViDateTimestamp` khi sắp xếp ngày tháng trong `SmartTableRenderer.tsx`.

---

## 🟠 LỖI 3 [MEDIUM-HIGH]: `MessageBubble` bỏ sót Citation `[N]` trong thẻ in đậm/in nghiêng và gây lỗi HTML DOM Nesting (`<div>` trong `<p>`)

### Vị trí
- `frontend/src/components/chat/MessageBubble.tsx` (dòng 40–99)
- `frontend/src/components/chat/CitationBadge.tsx` (dòng 20–58)

### Nguyên nhân
1. Trong `MessageBubble.tsx` (dòng 76–99), custom renderer cho `p` và `li` chỉ kiểm tra `typeof child === 'string' ? renderTextWithCitations(child) : child` ở cấp con trực tiếp:
   ```tsx
   p: ({ children }) => (
     <p className="mb-2 last:mb-0 leading-relaxed">
       {React.Children.map(children, (child) =>
         typeof child === 'string' ? renderTextWithCitations(child) : child
       )}
     </p>
   ),
   ```
   Khi LLM viết câu trả lời có citation nằm trong thẻ nhấn mạnh như `**150.000.000 VNĐ [1]**`, `*theo quy định [2]*`, hoặc trong ô bảng `<td>`, `child` là một React Element (`<strong>`, `<em>`), nên `[1]` **không được chuyển thành `<CitationBadge />`** mà hiển thị dạng text thô `[1]`.
2. Ngược lại, khi `<CitationBadge />` được render bên trong thẻ `<p>`, phần hover popover trong `CitationBadge.tsx` (dòng 30–56) lại sử dụng các thẻ block `<div>`, `<h4>`, `<p>`. Theo chuẩn HTML5 và React DOM, đặt `<div>`/`<h4>`/`<p>` bên trong `<p>` là cấu trúc DOM bất hợp lệ (`Warning: validateDOMNesting(...): <div> cannot appear as a descendant of <p>`).

### Cách khắc phục yêu cầu
1. Trong `MessageBubble.tsx`:
   - Viết hàm đệ quy `renderNodesWithCitations(nodes: React.ReactNode): React.ReactNode` sử dụng `React.Children.map`:
     - Nếu `typeof node === 'string'`, gọi `renderTextWithCitations(node)`.
     - Nếu `React.isValidElement(node)` và `node.props?.children` tồn tại (và không phải thẻ `code` / `pre`), dùng `React.cloneElement(node, { ...node.props, children: renderNodesWithCitations(node.props.children) })`.
   - Áp dụng `renderNodesWithCitations` cho `p`, `li`, `td`, `blockquote`.
2. Trong `CitationBadge.tsx`:
   - Thay thế toàn bộ thẻ `<div>`, `<h4>`, `<p>` bên trong popover (dòng 30–56) bằng thẻ `<span className="block ...">` (hoặc `<span className="flex ...">`) để hợp lệ 100% về mặt ngữ nghĩa HTML khi nằm trong `<p>`.

---

## 🟠 LỖI 4 [MEDIUM]: Tác vụ nạp tệp bị lỗi (`FAILED`) biến mất ngay lập tức khiến người dùng không đọc được nguyên nhân lỗi

### Vị trí
- `frontend/src/components/files/FileVaultDrawer.tsx` (dòng 39–47)
- `frontend/src/components/files/IngestionJobTracker.tsx` (dòng 32–37)

### Nguyên nhân
- Khi job chuyển sang trạng thái `SUCCESS` hoặc `FAILED`, `IngestionJobTracker` gọi ngay `onFinished(job)`.
- Trong `FileVaultDrawer.tsx` (dòng 39–46):
  ```ts
  const handleJobFinished = (finishedJob: IngestionJobDTO) => {
    setActiveJobs((prev) => prev.filter((j) => j.job_id !== finishedJob.job_id));
    refetchFiles();
  };
  ```
- Vì `handleJobFinished` xóa ngay `job_id` khỏi `activeJobs`, nên khi một tệp nạp bị lỗi (`status === 'FAILED'`), khung `IngestionJobTracker` chứa thông báo `job.error_message` vừa xuất hiện đã bị gỡ bỏ khỏi DOM ngay lập tức. Người dùng không thể biết tại sao tệp tải lên bị lỗi xử lý.

### Cách khắc phục yêu cầu
- Khi `finishedJob.status === 'SUCCESS'`: gọi `refetchFiles()`, và có thể giữ thẻ báo thành công trong khoảng `1500ms` trước khi tự động ẩn khỏi `activeJobs`.
- Khi `finishedJob.status === 'FAILED'`: gọi `refetchFiles()` nhưng **không tự động xóa ngay khỏi `activeJobs`**; thay vào đó hiển thị nút đóng (`X` / "Đã hiểu") trên `IngestionJobTracker` để người dùng đọc rõ `job.error_message` rồi tự đóng.

---

## 🟠 LỖI 5 [MEDIUM]: `POST /chat` không cập nhật `updated_at` của `ChatSessionModel` khi hội thoại tiếp trong phiên cũ

### Vị trí
- `api/routes/chat.py` (dòng 108–137)

### Nguyên nhân
- Khi người dùng gửi tin nhắn mới vào một `session_id` đã tồn tại, Backend truy vấn `chat_session` và thêm `user_msg`, `assistant_msg` vào bảng `chat_messages`, nhưng không cập nhật `chat_session.updated_at = utc_now()`.
- Trong SQLAlchemy, `onupdate=utc_now` trên `ChatSessionModel` chỉ kích hoạt khi chính bản ghi `ChatSessionModel` có cột bị `UPDATE`. Hệ quả là `updated_at` của phiên chat cũ giữ nguyên thời điểm tạo ban đầu, khiến `GET /sessions` (`order_by(ChatSessionModel.updated_at.desc())`) và phần phân nhóm thời gian trên `Sidebar` không đẩy phiên vừa tương tác lên đầu danh sách.

### Cách khắc phục yêu cầu
- Trong `api/routes/chat.py`:
  - Import `utc_now` từ `infrastructure.database.models`.
  - Khi thêm tin nhắn vào `chat_session` đã tồn tại (hoặc khi lưu `assistant_msg`), gán `chat_session.updated_at = utc_now()` trước khi `db.commit()`.
  - Bổ sung kiểm tra hoặc cập nhật test trong `tests/test_api.py` để xác nhận `updated_at` được làm mới khi chat tiếp.

---

## 🟡 LỖI 6 [MEDIUM]: Gán cứng `message.tables[0]` cho mọi bảng Markdown trong cùng một tin nhắn

### Vị trí
- `frontend/src/components/chat/MessageBubble.tsx` (dòng 37–38, 130–134)
- `frontend/src/components/chat/SmartTableRenderer.tsx` (dòng 86–90, 211–227)

### Nguyên nhân
- Khi kết quả truy vấn bảng có `> 50` dòng, `OutputFormatter` ở Backend sinh ra **2 bảng Markdown** trong cùng một `answer_markdown`:
  1. Bảng 1: 20 dòng dữ liệu đầu tiên.
  2. Bảng 2: Bảng `📊 Thống kê tóm tắt các cột số` (5 dòng: Count, Mean, Min, Max, Sum).
- Hiện tại `MessageBubble.tsx` (dòng 131) truyền cứng `meta={firstTableMeta}` (`message.tables[0]`) cho **tất cả** các thẻ `<table>` được `ReactMarkdown` render. Hệ quả là bảng thống kê tóm tắt (5 dòng) cũng bị gắn nhãn `Sheet1` và chân trang hiển thị sai: *"Hiển thị 5 / 120 dòng (Dữ liệu đã được rút gọn trên giao diện chat)"*.

### Cách khắc phục yêu cầu
- Trong `SmartTableRenderer.tsx` (hoặc `MessageBubble.tsx`):
  - Đối chiếu danh sách cột `headers` thực tế của bảng đang render với `meta?.columns`.
  - Nếu bảng đang render là bảng thống kê tóm tắt (ví dụ cột đầu tiên là `"Chỉ số thống kê"` hoặc `headers` không khớp với `meta.columns`), không áp dụng `meta.total_rows` / `meta.sheet_name` của bảng dữ liệu gốc cho bảng thống kê đó.

---

## 🟡 LỖI 7 [LOW]: Khớp tiền tố đường dẫn trong `serve_spa_catchall` (`api/main.py`) chưa chặt chẽ

### Vị trí
- `api/main.py` (dòng 140–157)

### Nguyên nhân
- Trong `serve_spa_catchall`, câu lệnh:
  ```python
  api_prefixes = ("api/", "docs", "redoc", "openapi.json", "health", "me", "upload", "files", "chat", "sessions", "feedback")
  if full_path.startswith(api_prefixes):
      raise HTTPException(status_code=404, detail="API endpoint not found")
  ```
  sử dụng `startswith` trên chuỗi thô. Nếu sau này Frontend có route client như `/chat-history` hoặc `/files-vault`, `full_path.startswith("chat")` sẽ chặn nhầm và trả về 404 khi người dùng F5 trình duyệt.

### Cách khắc phục yêu cầu
- Tách segment đầu tiên của đường dẫn để kiểm tra chính xác:
  ```python
  first_segment = full_path.strip("/").split("/")[0]
  reserved_segments = {"api", "docs", "redoc", "openapi.json", "health", "me", "upload", "files", "chat", "sessions", "feedback"}
  if first_segment in reserved_segments:
      raise HTTPException(status_code=404, detail="API endpoint not found")
  ```

# Báo Cáo Review Lần 2 — Các Lỗi Phát Sinh & Điểm Cần Hoàn Thiện (`fix_ver2.md`)

**Ngày kiểm tra:** 2026-10-26  
**Trạng thái bộ test hiện tại:** `65/65 passed` (tuy nhiên có 2 lỗi runtime nghiêm trọng bị bộ test bỏ lọt do cách viết assertion trong test).

---

## Phần 1: Các hạng mục từ `fix_ver1.md` ĐÃ ĐƯỢC SỬA TỐT

1. **Khởi tạo Services & Model Signatures (`api/dependencies/services.py`):**
   - `OpenAILLMClient.__init__` đã nhận `temperature` và `max_tokens`.
   - `BGEM3Embedder.__init__` và `BGEReranker.__init__` đã hỗ trợ `model_path`, tự động bật `use_fp16=True` khi chạy trên `cuda`, và giới hạn `batch_size=12, max_length=512` trong `BGEM3Embedder.encode` để bảo vệ GPU 4GB VRAM.
2. **Đồng bộ `async/await` & Chuẩn hóa đầu ra `Embedder`:**
   - `RAGEngine.answer_query` đã chuyển sang `async def`, kiểm tra `inspect.isawaitable` và được `await` đúng tại `api/routes/chat.py` và `HybridEngine.execute`.
   - `CatalogService.generate_and_validate_fewshots` và `Router.cosine_similarity` đã trích xuất đúng vector `"dense"` từ `dict` trả về của `BGEM3Embedder`.
3. **Đồng bộ Payload Qdrant & DTO Attributes:**
   - `DocIngestor.ingest_file` đã lưu song song cả `"content"` / `"text"` và `"page_number"` / `"page"`.
   - `RAGExecutionResult` đã bổ sung property `citations` và `OutputFormatter.format_dataframe_for_display` đã được thêm đầy đủ.
   - `api/routes/chat.py` đã truyền đầy đủ `column_alias`, `column_name`, `dtype`, `min_val`, `max_val` cho column schema và `sql_query`, `table_id`, `embedding` cho few-shot examples.
4. **Kết nối đầy đủ luồng nghiệp vụ tại `api/routes/upload.py` & `api/routes/chat.py`:**
   - Đã truyền `llm_client` và `embedder` vào `CatalogService` khi ingest bảng.
   - Đã tính `consecutive_clarifications` từ lịch sử hội thoại, lọc & xếp hạng few-shot theo `table_id` + cosine similarity, gọi `EntityLinker.link_entities` trước khi chạy Tabular/Hybrid Engine, và ghi `AuditLogModel` cho cả upload lẫn chat.
5. **Hardening Sandbox & RBAC:**
   - `secure_code_executor.py` đã chặn `LOAD`/`EXPORT`/`CALL` trong DuckDB, chặn các hàm `.read_*` / `.to_*` trong AST của Pandas và xóa các hàm I/O khỏi module `pd`/`np` trong worker process.
   - `CatalogService.validate_sql_query` đã gọi `validate_duckdb_sql` và khóa `enable_external_access = false`.
   - `api/routes/upload.py` đã trả về HTTP `415`, kiểm tra trùng lặp SHA-256 theo phạm vi RBAC, và kiểm tra quyền truy cập trên `GET /upload/{job_id}`.

---

## Phần 2: 2 Lỗi Runtime Nghiêm Trọng (Critical Bugs) Cần Sửa Ngay

### 🔴 Lỗi 1: Gọi sai chữ ký hàm trong `ExcelPreprocessor._process_csv_file`
- **File:** `application/services/excel_preprocessor.py` (dòng 270–278)
- **Hiện trạng lỗi:**
  Khi xử lý file `.csv`, hàm `_process_csv_file` gọi 3 phương thức nội bộ nhưng truyền sai số lượng và kiểu đối số (khác với cách gọi đúng trong `process_excel_file` ở dòng 149–176):
  1. **Dòng 271:**
     ```python
     norm_df = self._normalize_column_types(df, clean_cols, aliases, warnings)
     ```
     Trong khi định nghĩa hàm tại dòng 583 là:
     ```python
     def _normalize_column_types(self, df: pd.DataFrame, warnings: List[str]) -> Tuple[pd.DataFrame, Dict[str, str]]:
     ```
     Hàm chỉ nhận **2 tham số** `(df, warnings)` và trả về một `Tuple[pd.DataFrame, Dict[str, str]]`. Truyền 4 tham số sẽ gây lỗi ngay lập tức:
     `TypeError: ExcelPreprocessor._normalize_column_types() takes 3 positional arguments but 5 were given`.
  2. **Dòng 274:**
     ```python
     distinct_vals = self._extract_distinct_values(norm_df, aliases)
     ```
     Trong khi định nghĩa hàm tại dòng 769 là:
     ```python
     def _extract_distinct_values(self, df: pd.DataFrame, col_types: Dict[str, str]) -> Dict[str, List[str]]:
     ```
     Hàm yêu cầu tham số thứ 2 là `col_types` (`Dict[str, str]`, vì dòng 774 gọi `col_types.items()`), nhưng code lại truyền `aliases` (`List[str]`), gây lỗi:
     `AttributeError: 'list' object has no attribute 'items'`.
  3. **Dòng 277:**
     ```python
     col_schema = self._build_column_schema(norm_df, clean_cols, aliases)
     ```
     Trong khi định nghĩa hàm tại dòng 791 là:
     ```python
     def _build_column_schema(
         self,
         df: pd.DataFrame,
         cleaned_names: List[str],
         column_aliases: List[str],
         col_types: Dict[str, str],
     ) -> List[Dict[str, Any]]:
     ```
     Thiếu tham số thứ 4 `col_types`, gây lỗi `TypeError`.

- **Lý do test chưa phát hiện ra:**
  Trong `tests/test_api.py` (dòng 246–267), hàm `test_upload_csv_success_and_poll_status` chỉ kiểm tra `assert poll_res.status_code == 200` và `assert poll_res.json()["job_id"] == job_id`, mà không kiểm tra `assert poll_res.json()["status"] == "SUCCESS"`. Thực tế background task xử lý CSV đã bị crash và rơi vào trạng thái `"FAILED"`.

- **Cách sửa chuẩn tại `application/services/excel_preprocessor.py` (dòng 270–278):**
  Thay đoạn dòng 270–278 bằng:
  ```python
        # 3. Chuẩn hóa kiểu dữ liệu (số VN, ngày tháng, tiền tệ)
        df.columns = aliases
        norm_df, col_types = self._normalize_column_types(df, warnings)

        # 4. Trích xuất distinct values cho các cột phân loại
        distinct_vals = self._extract_distinct_values(norm_df, col_types)

        # 5. Xây dựng schema cột
        col_schema = self._build_column_schema(norm_df, clean_cols, aliases, col_types)
  ```

---

### 🔴 Lỗi 2: Dùng nhầm biến `response_model` thay vì `target_model` trong `OpenAILLMClient.structured_output`
- **File:** `infrastructure/llm/openai_llm_client.py` (dòng 275 và dòng 297)
- **Hiện trạng lỗi:**
  Ở dòng 201–215 của `structured_output`, hàm đã phân giải model Pydantic đích vào biến `target_model` để hỗ trợ cả cách gọi truyền đối số vị trí `structured_output(messages, ResponseModel)` (khi đó tham số keyword `response_model` vẫn là `None`) lẫn cách gọi truyền keyword `response_model=ResponseModel`.
  Tuy nhiên, ở phần thân hàm bên dưới:
  - **Dòng 275:**
    ```python
    parsed_instance = response_model.model_validate_json(clean_json_str)
    ```
  - **Dòng 297:**
    ```python
    f"Invalid JSON or Schema Validation failed for {response_model.__name__} "
    ```
  Khi `CatalogService._generate_table_summary` (dòng 140) hoặc `CatalogService.generate_and_validate_fewshots` (dòng 168) gọi `self.llm_client.structured_output(messages, TableSummaryOutput)` theo vị trí, `response_model` sẽ bằng `None` và ném ra ngoại lệ:
  `AttributeError: 'NoneType' object has no attribute 'model_validate_json'`.

- **Cách sửa chuẩn tại `infrastructure/llm/openai_llm_client.py`:**
  - Tại **dòng 275**, đổi `response_model.model_validate_json(clean_json_str)` thành:
    ```python
    parsed_instance = target_model.model_validate_json(clean_json_str)
    ```
  - Tại **dòng 297**, đổi `response_model.__name__` thành:
    ```python
    f"Invalid JSON or Schema Validation failed for {target_model.__name__} "
    ```

---

## Phần 3: Các Điểm Nhỏ Về Tính Nhất Quán & Kiểm Thử (Minor Consistency & Test Improvements)

### 🟡 1. Bỏ ràng buộc `UNIQUE` toàn cục trên `sha256_hash` trong `scripts/schema.sql`
- **File:** `scripts/schema.sql` (dòng 35)
- **Hiện trạng:** Trong `infrastructure/database/models.py` (dòng 63), `FileModel.sha256_hash` đã bỏ `unique=True` để cho phép 2 phòng ban khác nhau upload cùng một file mà không bị lỗi `UniqueViolation`. Tuy nhiên trong `scripts/schema.sql` dòng 35 vẫn còn:
  ```sql
  sha256_hash VARCHAR(64) NOT NULL UNIQUE,
  ```
- **Cách sửa:** Đổi dòng 35 của `scripts/schema.sql` thành:
  ```sql
  sha256_hash VARCHAR(64) NOT NULL,
  ```

### 🟡 2. Bỏ định dạng `.doc` khỏi `SUPPORTED_DOCUMENTS` trong `api/routes/upload.py`
- **File:** `api/routes/upload.py` (dòng 55)
- **Hiện trạng:** `SUPPORTED_DOCUMENTS = {".pdf", ".docx", ".doc", ".md", ".txt"}` vẫn chứa `".doc"`, trong khi `python-docx` không hỗ trợ đọc file `.doc` nhị phân cũ (sẽ lỗi khi vào background task) và thông báo lỗi ở dòng 216 cũng chỉ liệt kê `.xlsx, .csv, .pdf, .docx, .md, .txt`.
- **Cách sửa:** Đổi dòng 55 của `api/routes/upload.py` thành:
  ```python
  SUPPORTED_DOCUMENTS = {".pdf", ".docx", ".md", ".txt"}
  ```

### 🟡 3. Fallback key payload trong `RAGEngine._expand_context`
- **File:** `application/services/rag_engine.py` (dòng 348–368)
- **Hiện trạng:** Mặc dù `DocIngestor` đã lưu cả hai bộ key (`page`/`page_number` và `text`/`content`), hàm `_expand_context` ở dòng 349 và 368 vẫn chỉ đọc `payload.get("page")` và `payload.get("text", "")`.
- **Cách sửa:** Đổi thành:
  - Dòng 349: `p_page = payload.get("page") if payload.get("page") is not None else payload.get("page_number")`
  - Dòng 368: `merged_text = "\n\n".join(p.get("text") or p.get("content") or "" for p in group_sorted)`

### 🟡 4. Bổ sung kiểm tra `status == "SUCCESS"` cho test upload CSV & Excel trong `tests/test_api.py`
- **File:** `tests/test_api.py` (dòng 265–267 và dòng 297)
- **Hiện trạng:** `test_upload_csv_success_and_poll_status` chưa kiểm tra `poll_res.json()["status"] == "SUCCESS"`, khiến lỗi trong background task khi xử lý CSV không làm test fail.
- **Cách sửa:** Thêm `assert poll_res.json()["status"] == "SUCCESS"` vào dòng 267 của `tests/test_api.py`.

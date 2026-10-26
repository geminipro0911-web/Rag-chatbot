# Danh sách lỗi và hạng mục cần sửa đổi — Phiên bản 1 (`fix_ver1.md`)

Tài liệu này tổng hợp toàn bộ các lỗi runtime, lỗ hổng bảo mật, luồng tính năng bị bỏ sót và các điểm chưa khớp với đặc tả trong `Prompt.md` sau khi rà soát mã nguồn hiện tại.

---

## 1. Lỗi Crash Runtime nghiêm trọng (Ưu tiên P0 — Phải sửa ngay)

Các lỗi dưới đây không bị phát hiện khi chạy `pytest` vì `tests/test_api.py` đã dùng Mock (`MockLLMClient`, `MockEmbedder`, `MockReranker`, `MockTabService`) che khuất sự lệch pha giữa các module. Khi chạy thật sẽ crash ngay lập tức.

### 1.1. Lệch chữ ký hàm (Method Signature) ở `OpenAILLMClient`
- **Vấn đề 1 — Khởi tạo dư tham số:**
  - Tại `api/dependencies/services.py` (dòng 54–62), hàm `get_llm_client()` khởi tạo:
    ```python
    _llm_client = OpenAILLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model_name=settings.llm_model_name,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    ```
  - Tuy nhiên, `OpenAILLMClient.__init__` tại `infrastructure/llm/openai_llm_client.py` (dòng 33–40) **không nhận** `temperature` và `max_tokens` → Ném `TypeError: OpenAILLMClient.__init__() got an unexpected keyword argument 'temperature'`.
  - **Cách sửa:** Bổ sung `temperature` và `max_tokens` vào `OpenAILLMClient.__init__`.

- **Vấn đề 2 — Gọi `structured_output()` sai tham số:**
  - Định nghĩa tại `application/interfaces/llm_client.py` (dòng 39) và `infrastructure/llm/openai_llm_client.py` (dòng 162) chỉ nhận:
    `structured_output(self, messages: List[Dict[str, str]], response_model: Type[T], temperature: float = 0.1, max_retries: int = 2)`
  - Nhưng ở 3 service cốt lõi lại gọi theo kiểu `prompt=...` và `system_prompt=...`:
    - `application/services/router.py` (dòng 203–208)
    - `application/services/entity_linker.py` (dòng 223–228 và 463–468)
    - `application/services/tabular_executor.py` (dòng 151–156)
  - **Cách sửa:** Cập nhật `LLMClient.structured_output` và `OpenAILLMClient.structured_output` (cũng như `chat_completion`) để hỗ trợ linh hoạt cả `messages: Optional[List[Dict[str, str]]] = None` lẫn `prompt: Optional[str] = None, system_prompt: Optional[str] = None` (tự động ghép `system_prompt` và `prompt` thành `messages` nếu `messages` không được truyền).

### 1.2. Sai tên tham số khi khởi tạo `BGEM3Embedder` và `BGEReranker`
- **Vấn đề:**
  - Tại `api/dependencies/services.py` (dòng 80 và 91), `get_embedder()` và `get_reranker()` truyền `model_path=...`.
  - Nhưng `BGEM3Embedder.__init__` (`infrastructure/models/bge_m3_embedder.py` dòng 31) và `BGEReranker.__init__` (`infrastructure/models/bge_reranker.py` dòng 26) lại đặt tên tham số là `model_name_or_path` → Ném `TypeError`.
- **Cách sửa:** Đổi tên tham số hoặc chấp nhận cả `model_path` lẫn `model_name_or_path` trong `__init__` của cả hai class; đồng thời truyền `use_fp16=True` khi `device` bắt đầu bằng `"cuda"`.

### 1.3. Lẫn lộn `async` / `sync` và kiểu dữ liệu trả về của `Embedder`
- **Vấn đề 1 — Thiếu `await` khi gọi `llm_client.chat_completion`:**
  - `OpenAILLMClient.chat_completion` là hàm `async def`.
  - Nhưng `RAGEngine.answer_query` (`application/services/rag_engine.py` dòng 85, 236, 268) là hàm đồng bộ (`def`) lại gọi trực tiếp `raw_answer = self.llm_client.chat_completion(...)` không có `await`. Kết quả `raw_answer` là một `coroutine` object thay vì `str` → Crash ở bước `OutputFormatter.audit_citations`.
  - Tại `application/services/hybrid_engine.py` (dòng 300 và 334), gọi `await asyncio.to_thread(self.llm_client.chat_completion, ...)` cũng chỉ trả về coroutine chưa được thực thi.
  - **Cách sửa:** Chuyển `RAGEngine.answer_query` thành `async def answer_query(...)` và dùng `await self.llm_client.chat_completion(...)` ở cả `rag_engine.py`, `hybrid_engine.py`, và `api/routes/chat.py` (dòng 290).

- **Vấn đề 2 — Dùng `await` cho hàm đồng bộ `embedder.embed_query`:**
  - `BGEM3Embedder.embed_query` (`infrastructure/models/bge_m3_embedder.py` dòng 62) là hàm đồng bộ (`def`).
  - Tại `application/services/catalog_service.py` (dòng 174), code gọi `emb_res = await self.embedder.embed_query(pair.question)` → Crash `TypeError: object dict can't be used in 'await' expression`.
  - **Cách sửa:** Bỏ `await` (hoặc kiểm tra `inspect.isawaitable`) khi gọi `self.embedder.embed_query`.

- **Vấn đề 3 — Truyền `dict` vào `cosine_similarity` trong `Router`:**
  - `embed_query()` trả về `Dict[str, Any]` (`{"dense": List[float], "sparse_indices": ..., "sparse_values": ...}`).
  - Tại `application/services/router.py` (dòng 311, 347–348, 378–390), code gán `query_embed = self.embedder.embed_query(query)` rồi truyền thẳng `query_embed` và `table_vec` vào `cosine_similarity(v1: List[float], v2: List[float])` → Crash `TypeError` trong `np.array(v1, dtype=np.float32)`.
  - **Cách sửa:** Trích xuất vector dense (`emb["dense"] if isinstance(emb, dict) else emb`) trước khi đưa vào `cosine_similarity`.

### 1.4. Lệch tên trường dữ liệu (Key/Attribute Mismatch) giữa các tầng
- **Vấn đề 1 — Mất trắng nội dung văn bản trong Document RAG (`content` vs `text`):**
  - Khi lưu chunk vào Qdrant tại `application/services/doc_ingestor.py` (dòng 152–167), payload sử dụng key `"content"` (nội dung văn bản) và `"page_number"` (số trang).
  - Nhưng khi đọc từ Qdrant tại `application/services/rag_engine.py` (dòng 142, 200, 202, 334, 350–354) và `application/services/output_formatter.py` (dòng 299), code lại đọc `payload.get("text", "")` và `payload.get("page")`!
  - **Hậu quả:** Reranker và LLM nhận chuỗi rỗng `""` cho mọi chunk tài liệu.
  - **Cách sửa:** Thống nhất dùng `payload.get("content") or payload.get("text", "")` và `payload.get("page_number") or payload.get("page")` ở cả `doc_ingestor.py`, `rag_engine.py`, và `output_formatter.py`.

- **Vấn đề 2 — Sai tên thuộc tính `rag_res.citations`:**
  - Tại `api/routes/chat.py` (dòng 297–298), code gọi `sources = rag_res.citations`, nhưng `RAGExecutionResult` (`application/services/rag_engine.py` dòng 45) chỉ có trường `sources` (không có `citations`) → Crash `AttributeError` khi chạy luồng `DOCUMENT`.
  - **Cách sửa:** Đổi `rag_res.citations` thành `rag_res.sources` trong `api/routes/chat.py`.

- **Vấn đề 3 — Gọi sai hàm `format_dataframe_for_display`:**
  - Tại `api/routes/chat.py` (dòng 247), code gọi `OutputFormatter.format_dataframe_for_display(df, max_rows=10, preview_rows=10)`.
  - Thực tế trong `application/services/output_formatter.py` (dòng 119), `format_dataframe_for_display` là hàm cấp module (không nằm trong class `OutputFormatter`), tham số tên là `head_rows` (không phải `preview_rows`), và trả về `Tuple[str, Optional[str]]`.
  - **Cách sửa:** Gọi `summary_df_md, _ = format_dataframe_for_display(df, max_rows=10, head_rows=10)` và gắn thêm `@staticmethod` hoặc alias trên `OutputFormatter` nếu cần.

- **Vấn đề 4 — Lệch key schema cột và few-shot giữa `chat.py` và `TabularExecutor`:**
  - Tại `api/routes/chat.py` (dòng 147–160), danh sách bảng gửi đi có cấu trúc:
    ```python
    "columns": [{"name": c.column_alias, "type": c.data_type, "sample_values": c.sample_values} ...]
    ```
    Nhưng `TabularExecutor._format_schema_prompt` (`application/services/tabular_executor.py` dòng 342–347) và `_get_valid_columns_summary` (dòng 397) lại đọc `c.get("column_alias")`, `c.get("column_name")`, `c.get("dtype")` → Tên cột bị `None` trong prompt sinh SQL!
  - Tại `api/routes/chat.py` (dòng 210), few-shot dict dùng key `"code": f.sql_query`, nhưng `TabularExecutor._format_fewshot_prompt` (`tabular_executor.py` dòng 382) lại đọc `ex.get("sql_query", "")` → Câu lệnh SQL mẫu trong prompt luôn bị rỗng!
  - **Cách sửa:** Chuẩn hóa dict trong `chat.py` có đủ `"column_alias": c.column_alias, "column_name": c.original_name, "dtype": c.data_type, "min_val": c.min_val, "max_val": c.max_val` và `"sql_query": f.sql_query, "table_id": f.table_id, "embedding": f.embedding`.

---

## 2. Các luồng tính năng đã viết nhưng bị bỏ sót khi ghép nối (Ưu tiên P1)

### 2.1. Background Job trong `upload.py` không truyền `llm_client`, `embedder`, `ocr_engine`
- **Vấn đề:**
  - Tại `api/routes/upload.py` (dòng 109), hàm `run_file_ingestion_job` khởi tạo `CatalogService(enable_synthetic_fewshot=settings.enable_synthetic_fewshot)` mà không truyền `llm_client` và `embedder`. Vì `self.llm_client` là `None`, hệ thống không bao giờ gọi LLM để sinh mô tả bảng/từ khóa và không bao giờ sinh synthetic few-shot khi upload file thật.
  - Tại dòng 142, `DocumentIngestor` cũng được khởi tạo mới mà không truyền `ocr_engine`.
- **Cách sửa:** Lấy `llm_client = get_llm_client()`, `embedder = get_embedder()` từ `api/dependencies/services.py` truyền vào `CatalogService`, và truyền `ocr_engine` vào `DocumentIngestor`.

### 2.2. Endpoint `/chat` bỏ quên `EntityLinker`
- **Vấn đề:**
  - Module `EntityLinker` (`application/services/entity_linker.py`) đã được viết hoàn chỉnh 5 tầng, nhưng trong `api/routes/chat.py` (dòng 225 và 301) lại không được gọi để truyền `entity_links` vào `tabular_svc.execute_query()` và `hybrid_svc.execute_hybrid()`.
- **Cách sửa:** Inject `entity_linker: EntityLinker = Depends(get_entity_linker)` vào `chat_endpoint`, chạy `entity_links = await entity_linker.link_entities(query=rewritten_query, candidate_tables=target_tables)` trước khi gọi Tabular/Hybrid Engine.

### 2.3. Chưa truyền `consecutive_clarifications` vào `Router.route_query`
- **Vấn đề:**
  - Tại `api/routes/chat.py` (dòng 188), `router_svc.route_query(...)` không được truyền `consecutive_clarifications`, nên luôn mặc định bằng `0`. Điều này làm hỏng chính sách "Tối đa 1 lần CLARIFY liên tiếp; lần sau phải trả lời theo giả định hợp lý nhất".
- **Cách sửa:** Đếm số tin nhắn `assistant` liên tiếp gần nhất trong `past_messages` có `route == "CLARIFY"` và truyền vào `route_query`.

### 2.4. Chọn Few-Shot Examples theo bảng và độ tương đồng (Cosine Similarity)
- **Vấn đề:**
  - Tại `api/routes/chat.py` (dòng 208), code đang lấy toàn bộ `FewShotExampleModel` trong DB mà không lọc theo `table_id` của các bảng ứng viên (gây nhiễu prompt và rò rỉ cấu trúc bảng của phòng ban khác) và chưa sắp xếp theo độ tương đồng vector với câu hỏi.
- **Cách sửa:** Chỉ truy vấn `FewShotExampleModel` có `table_id.in_(target_table_ids)`, ưu tiên `source == 'verified'`, kết hợp tính cosine similarity giữa `embedding` của câu hỏi và `f.embedding` để lấy Top-3.

---

## 3. Lỗ hổng Bảo mật, Sandbox & Phân quyền RBAC (Ưu tiên P1)

### 3.1. Lỗ hổng thoát Sandbox trong Pandas (`secure_code_executor.py`)
- **Vấn đề:**
  - Trong `_run_pandas_sandbox_worker` (`infrastructure/sandbox/secure_code_executor.py` dòng 279–292), toàn bộ module `pandas` (`pd`) và `numpy` (`np`) được đưa trực tiếp vào `safe_globals`.
  - Dù AST đã chặn `open()` và các thuộc tính `__x__`, code vẫn có thể đọc/ghi file trái phép trên máy chủ thông qua `pd.read_parquet(...)`, `pd.read_csv(...)`, `pd.read_excel(...)`, `pd.to_pickle(...)`, hoặc thực thi lệnh hệ thống qua `pd.io.common.os.system(...)` (vì `io`, `common`, `os`, `system` không có dấu `__`).
- **Cách sửa:**
  1. Trong `BANNED_PANDAS_CALLS` (AST validation), chặn tất cả các phương thức bắt đầu bằng `read_`, `to_` (trừ `to_datetime`, `to_numeric`, `to_frame`, `to_dict`, `to_list`), `loadtxt`, `load`, `save`, `fromfile`.
  2. Chặn truy cập các thuộc tính nguy hiểm trên AST (`io`, `os`, `sys`, `subprocess`, `shutil`, `pathlib`, `ctypes`, `builtins`, `_builtins`).
  3. Trong worker subprocess, trước khi `exec`, xóa hoặc vô hiệu hóa các hàm I/O của `pd` và `np` (hoặc tạo proxy object chỉ phơi bày các hàm tính toán an toàn của `pd` như `DataFrame`, `Series`, `concat`, `merge`, `pivot_table`, `crosstab`, `cut`, `qcut`, `to_datetime`, `to_numeric`, `isna`, `notna`, `date_range`).
  4. Bổ sung giới hạn bộ nhớ trên Windows bằng `win32job` (`pywin32`) khi `sys.platform == "win32"`.

### 3.2. Khóa chặt DuckDB Sandbox ở mọi nơi (`secure_code_executor.py` & `catalog_service.py`)
- **Vấn đề:**
  - Trong `PROHIBITED_SQL_ROOT_NAMES` (`secure_code_executor.py` dòng 33), còn thiếu `"load"` và `"export"`.
  - Trong `CatalogService.validate_sql_query` (`catalog_service.py` dòng 225–238), khi chạy thử synthetic SQL do LLM sinh ra, code tạo kết nối DuckDB trực tiếp mà **không** đi qua `validate_duckdb_sql` (sqlglot) và **không** bật `SET enable_external_access=false`.
- **Cách sửa:**
  - Thêm `"load"`, `"export"`, `"call"` vào `PROHIBITED_SQL_ROOT_NAMES`.
  - Trong `CatalogService.validate_sql_query`, gọi `validate_duckdb_sql(clean_sql)` và thiết lập `SET enable_external_access=false; SET lock_configuration=true;` sau khi nạp bảng vào bộ nhớ.

### 3.3. Cô lập RBAC trong Deduplication và Polling Job (`upload.py`)
- **Vấn đề:**
  - `FileModel.sha256_hash` đang là `unique=True` toàn hệ thống (`upload.py` dòng 227). Nếu Phòng A upload một file nội bộ (`is_public=False`), sau đó Phòng B upload cùng file đó, Phòng B nhận phản hồi `DUPLICATE` nhưng không có quyền truy cập file của Phòng A.
  - `GET /upload/{job_id}` (`upload.py` dòng 294) không kiểm tra quyền truy cập của user đối với `job.file`.
- **Cách sửa:**
  - Khi kiểm tra trùng lặp SHA-256, chỉ báo `DUPLICATE` nếu file đã tồn tại thuộc cùng `department_id` hoặc `is_public=True` hoặc cùng `owner_user_id` (đồng thời đổi unique constraint trên `sha256_hash` thành index thường hoặc composite unique `(sha256_hash, department_id)`).
  - Tại `GET /upload/{job_id}`, kiểm tra RBAC trên `job.file` trước khi trả kết quả.

---

## 4. Chuẩn hóa theo cấu hình Phần cứng & Yêu cầu trong `Prompt.md` (Ưu tiên P2)

### 4.1. Tối ưu cho GPU A400 (4GB VRAM) và 16GB RAM
- **Vấn đề:** Cấu hình phần cứng trong `Prompt.md` là `i7-14700, 16GB RAM, GPU A400 4GB VRAM`.
- **Cách sửa:**
  - Bật `use_fp16=True` mặc định cho `BGEM3Embedder` khi chạy trên `cuda` để giảm một nửa VRAM (~1.1GB thay vì ~2.3GB).
  - Giới hạn `batch_size=12` và `max_length=512` khi gọi `self._model.encode(...)` trong `bge_m3_embedder.py` để tránh lỗi `CUDA out of memory` khi инgest file PDF dài.

### 4.2. Định dạng File Upload (`.xlsx`, `.csv`) và mã HTTP 415
- **Vấn đề:**
  - `Prompt.md` (dòng 41) quy định: Bảng = `.xlsx`, `.csv`; Văn bản = `.pdf`, `.docx`, `.md`, `.txt`; định dạng khác trả **HTTP 415**.
  - Hiện tại `api/routes/upload.py` (dòng 51, 205) đang đặt `SUPPORTED_TABULAR = {".xlsx", ".xls"}` (thiếu `.csv`, thừa `.xls` mà `openpyxl` không đọc được) và trả `400 Bad Request` thay vì `415 Unsupported Media Type`.
- **Cách sửa:**
  - Đổi `SUPPORTED_TABULAR = {".xlsx", ".csv"}` và `SUPPORTED_DOCUMENTS = {".pdf", ".docx", ".md", ".txt"}`.
  - Hỗ trợ đọc `.csv` trong `ExcelPreprocessor.process_file` (tự động nhận diện encoding `utf-8-sig`/`utf-8`/`cp1258`/`latin1` và delimiter, sau đó chạy chung pipeline làm sạch cột, chuẩn hóa kiểu dữ liệu, trích xuất distinct values và xuất `.parquet`).
  - Trả mã `status.HTTP_415_UNSUPPORTED_MEDIA_TYPE` khi sai định dạng.

### 4.3. Bổ sung Docling, OCR tiếng Việt và Tokenizer chuẩn trong `doc_ingestor.py`
- **Vấn đề:**
  - `doc_ingestor.py` chưa có nhánh thử dùng `Docling` (với `artifacts_path` offline) trước khi fallback về `PyMuPDF`/`python-docx`.
  - Hàm `_tokenize` đang dùng regex tách khoảng trắng thay vì dùng tokenizer của `bge-m3` (khi có sẵn).
  - Chưa có class thực thi `OCREngine` (kết hợp PaddleOCR + VietOCR) trong `infrastructure/models/`.
- **Cách sửa:**
  - Tạo `infrastructure/models/viet_ocr_engine.py` thực thi `OCREngine` (nạp trọng số local từ `settings.vietocr_weights_path` + PaddleOCR, có fallback an toàn khi chạy môi trường chưa có model).
  - Tích hợp Docling (nếu thư viện và `settings.docling_models_path` tồn tại) vào `doc_ingestor.py`, fallback mượt về PyMuPDF / python-docx.
  - Sử dụng tokenizer của `BGEM3Embedder` (hoặc `transformers.AutoTokenizer`) trong `_tokenize`/`_detokenize` nếu model đã nạp, fallback về regex khi chạy offline test.

### 4.4. Ghi đầy đủ Audit Log
- **Vấn đề:** Nguyên tắc 6 yêu cầu ghi audit log cho mọi upload, truy vấn, và code được thực thi. Hiện mới chỉ ghi ở `DELETE /files` và `POST /feedback`.
- **Cách sửa:** Ghi bản ghi `AuditLogModel` tại `POST /upload` (`action="UPLOAD_FILE"`) và `POST /chat` (`action="CHAT_QUERY"`, kèm `route`, `rewritten_query`, và `executed_code` nếu có trong `details`).

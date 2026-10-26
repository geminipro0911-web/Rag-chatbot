# Báo Cáo Review Lần 3 — Lỗi Tích Hợp Liên Module & RBAC (`fix_ver3.md`)

**Ngày kiểm tra:** 2026-10-26  
**Trạng thái các mục từ `fix_ver2.md`:** Đã được sửa hoàn toàn 100% (`65/65 passed`, bao gồm cả test upload CSV `status == "SUCCESS"`).

Dưới đây là **7 lỗi logic tích hợp liên module (Integration & Edge-case Logic)** được phát hiện khi rà soát sâu toàn bộ luồng dữ liệu từ lúc Upload $\rightarrow$ Ingest $\rightarrow$ Routing $\rightarrow$ Execution $\rightarrow$ Feedback.

---

## Nhóm 1: Lỗi Tích Hợp & Mất Tính Năng Ở Runtime (High Severity)

### 🔴 Lỗi 1: `get_entity_linker` quên truyền `llm_client` (Làm tê liệt Tier 1 & Tier 5 của Entity Linker)
- **File liên quan:**
  - `api/dependencies/services.py` (dòng 139–144)
  - `application/services/entity_linker.py` (dòng 329–332)
- **Hiện trạng lỗi:**
  1. Tại `api/dependencies/services.py` (dòng 139–144):
     ```python
     def get_entity_linker(
         db: Session = Depends(get_db),
     ) -> EntityLinker:
         """Provides entity normalization and disambiguation service."""
         return EntityLinker(db_session=db)
     ```
     Hàm khởi tạo không truyền `llm_client` vào `EntityLinker` (`self.llm_client = None`).
  2. Khi `self.llm_client` là `None`:
     - **Tier 1 (`extract_mentions`, dòng 207):** Nhánh `if self.llm_client:` bị bỏ qua hoàn toàn! Hệ thống chỉ chạy regex fallback (chỉ bắt được từ viết tắt có sẵn trong từ điển, cụm từ trong ngoặc kép `"..."`, hoặc từ viết IN HOA). Mọi thực thể tiếng Việt thông thường trong câu hỏi (như `"chi nhánh miền Bắc"`, `"máy tính Dell"`) đều không được trích xuất.
     - **Tier 5 (`link_entities`, dòng 441):** Nhánh `if combined_candidates and self.llm_client:` không bao giờ chạy! Tính năng dùng LLM phân giải nhập nhằng khi điểm RapidFuzz nằm trong khoảng 70–89 hoặc có nhiều ứng viên trùng điểm bị vô hiệu hóa hoàn toàn.
  3. Tại `application/services/entity_linker.py` (dòng 330–331):
     ```python
     if extracted_mentions is None:
         extracted_mentions = await self.extract_mentions(query)
     ```
     Hàm `link_entities` gọi `self.extract_mentions(query)` nhưng quên truyền `catalog_columns` được gom từ `candidate_tables`, khiến prompt trích xuất thực thể của LLM không biết bảng có những cột nào.

- **Cách sửa chuẩn:**
  1. Trong `api/dependencies/services.py` (dòng 139–144), sửa thành:
     ```python
     def get_entity_linker(
         db: Session = Depends(get_db),
         llm: LLMClient = Depends(get_llm_client),
     ) -> EntityLinker:
         """Provides entity normalization and disambiguation service."""
         return EntityLinker(llm_client=llm, db_session=db)
     ```
  2. Trong `application/services/entity_linker.py` (dòng 329–332), sửa thành:
     ```python
        # Tier 1: Extract mentions
        if extracted_mentions is None:
            catalog_cols: List[Dict[str, str]] = []
            if candidate_tables:
                for tbl in candidate_tables:
                    for col in tbl.get("columns", []):
                        if isinstance(col, dict):
                            catalog_cols.append(col)
            extracted_mentions = await self.extract_mentions(query, catalog_columns=catalog_cols or None)
     ```

---

### 🔴 Lỗi 2: Tên file gốc và tên bảng CSV bị dính tiền tố `UUID_` khi lưu tại `upload.py`
- **File liên quan:**
  - `api/routes/upload.py` (dòng 152, 168, 261)
  - `application/services/excel_preprocessor.py` (dòng 107, 239–240)
  - `application/services/doc_ingestor.py` (dòng 97, 184)
- **Hiện trạng lỗi:**
  Khi người dùng upload file (ví dụ `doanh_thu_q1.csv` hoặc `Quy_che_tai_chinh.pdf`), tại `api/routes/upload.py` dòng 261, hệ thống lưu file xuống đĩa với tên:
  ```python
  stored_filename = f"{file_id}_{Path(filename).name}"
  ```
  Sau đó truyền `file_path = raw_storage_path` vào `run_file_ingestion_job`.
  - Trong `ExcelPreprocessor.process_excel_file` (dòng 107) và `_process_csv_file` (dòng 239–240):
    ```python
    source_file = os.path.basename(file_path)
    sheet_name = Path(source_file).stem
    ```
    Nếu `file_id` có trong tên file vật lý, `source_file` trở thành `"550e8400-e29b-41d4-a716-446655440000_doanh_thu_q1.csv"`, và `sheet_name` của bảng CSV lưu vào DB trở thành `"550e8400-e29b-41d4-a716-446655440000_doanh_thu_q1"` thay vì `"doanh_thu_q1"`!
  - Trong `DocumentIngestor.ingest_file` (dòng 97 & 184):
    `file_name = os.path.basename(file_path)` làm cho mọi chunk trong Qdrant (`payload["file_name"]`, `breadcrumb`), `DocumentModel.title`, và phần **📚 Chỉ mục nguồn trích dẫn** trả về cho người dùng đều bị dính chuỗi UUID 36 ký tự ở đầu tên file (ví dụ: `[1] 550e8400-..._Quy_che_tai_chinh.pdf`).
  - Ngoài ra, tại `api/routes/upload.py` dòng 152, `run_file_ingestion_job` đang gọi trực tiếp `vector_store = get_vector_store()` thay vì nhận `vector_store` qua Dependency Injection từ `upload_file` (làm bỏ qua `app.dependency_overrides[get_vector_store]` khi test upload tài liệu).

- **Cách sửa chuẩn:**
  1. Trong `ExcelPreprocessor.process_excel_file` (dòng 107) và `_process_csv_file` (dòng 239):
     Loại bỏ tiền tố `{file_id}_` khỏi `source_file`:
     ```python
     raw_basename = os.path.basename(file_path)
     source_file = raw_basename[len(file_id) + 1:] if file_id and raw_basename.startswith(f"{file_id}_") else raw_basename
     ```
  2. Trong `DocumentIngestor.ingest_file` (dòng 97):
     Loại bỏ tiền tố `{file_id}_` khỏi `file_name`:
     ```python
     raw_basename = os.path.basename(file_path)
     file_name = raw_basename[len(file_id) + 1:] if file_id and raw_basename.startswith(f"{file_id}_") else raw_basename
     ```
  3. Trong `api/routes/upload.py`:
     - Thêm `vector_store: Optional[VectorStore] = None` vào tham số của `run_file_ingestion_job` (dòng 99), dùng `effective_vs = vector_store or get_vector_store()` ở dòng 152, và sửa dòng 168 thành `doc_metadata={"file_name": res.title}`.
     - Tại `upload_file` (dòng 206), inject thêm `vector_store: VectorStore = Depends(get_vector_store)` và truyền `vector_store=vector_store` vào `background_tasks.add_task(...)` (dòng 322).

---

### 🔴 Lỗi 3: Lệch tên bảng (`table_alias` vs `sheet_name`) giữa Few-Shot, DuckDB SQL và Pandas Sandbox
- **File liên quan:**
  - `application/services/catalog_service.py` (dòng 121–123)
  - `application/services/tabular_executor.py` (dòng 105–113, 185–206, 333–336)
  - `infrastructure/sandbox/secure_code_executor.py` (dòng 426–437)
- **Hiện trạng lỗi:**
  1. Lúc ingest bảng, `CatalogService.generate_and_validate_fewshots` (dòng 121–123) tạo tên bảng quy ước:
     ```python
     table_alias = re.sub(r"[^a-zA-Z0-9_]+", "_", processed_sheet.sheet_name).strip("_").lower()
     if not table_alias or table_alias[0].isdigit():
         table_alias = f"tbl_{table_alias}"
     ```
     Vì vậy các câu lệnh SQL mẫu trong `fewshot_examples` đều viết `FROM doanh_thu_q1` (chữ thường, dấu gạch dưới).
  2. Nhưng lúc thực thi ở `TabularExecutor.execute_query` (dòng 105–113), `table_parquet_mapping` chỉ đăng ký `t_name` (tức `sheet_name` gốc, ví dụ `"Doanh Thu Q1"`) và `table["id"]` (UUID).
     - **Trong DuckDB SQL:** Nếu LLM học theo Few-Shot và sinh câu lệnh `SELECT ... FROM doanh_thu_q1`, DuckDB sẽ báo lỗi `Table with name doanh_thu_q1 does not exist`!
     - **Trong Python Pandas (`tabular_executor.py` dòng 185–199):** `table_dfs` truyền vào `safe_globals` có key là `"Doanh Thu Q1"` (chứa khoảng trắng) và UUID `"550e8400-..."` (chứa dấu `-`). Cả hai đều **không phải là tên biến Python hợp lệ**, và trong `safe_globals` cũng không có biến `df` mặc định! Nếu LLM viết code Pandas dùng `df` hoặc `doanh_thu_q1`, tiến trình con sẽ văng lỗi `NameError`.
     - **Nhân đôi RAM không cần thiết:** Trong `SecureCodeExecutor.execute_sql` (dòng 427–436) và `TabularExecutor` (dòng 187–190), vì `table_parquet_mapping` lưu nhiều key (`t_name`, `id`, `safe_alias`) cùng trỏ tới 1 đường dẫn `parquet_path`, vòng lặp hiện tại gọi `CREATE OR REPLACE TABLE ... AS SELECT * FROM read_parquet(...)` và `pd.read_parquet(p_path)` lặp lại nhiều lần cho cùng một file Parquet!

- **Cách sửa chuẩn:**
  1. Trong `TabularExecutor.execute_query` (`application/services/tabular_executor.py` dòng 105–113):
     Đăng ký thêm `safe_alias` vào `table_parquet_mapping`, và khi nạp `table_dfs` cho Python (dòng 185–194), chỉ đọc mỗi `parquet_path` 1 lần vào bộ nhớ đồng thời gán `table_dfs["df"]` cho bảng đầu tiên:
     ```python
        for table in candidate_tables:
            t_name = table.get("table_alias") or table.get("table_name") or table.get("name", "table_data")
            p_path = table.get("parquet_path")
            if p_path:
                table_parquet_mapping[t_name] = p_path
                safe_alias = re.sub(r"[^a-zA-Z0-9_]+", "_", str(t_name)).strip("_").lower()
                if not safe_alias or safe_alias[0].isdigit():
                    safe_alias = f"tbl_{safe_alias}"
                table_parquet_mapping[safe_alias] = p_path
                if table.get("id"):
                    table_parquet_mapping[table["id"]] = p_path
     ```
     Và tại nhánh `if current_lang == "python":` (dòng 185–194):
     ```python
            if current_lang == "python":
                loaded_by_path: Dict[str, pd.DataFrame] = {}
                for t_name, p_path in table_parquet_mapping.items():
                    if t_name not in table_dfs:
                        try:
                            if p_path not in loaded_by_path:
                                loaded_by_path[p_path] = pd.read_parquet(p_path)
                            table_dfs[t_name] = loaded_by_path[p_path]
                        except Exception as e:
                            logger.warning("Failed to load DataFrame for %s: %s", t_name, e)
                if loaded_by_path and "df" not in table_dfs:
                    table_dfs["df"] = next(iter(loaded_by_path.values()))
     ```
  2. Trong `SecureCodeExecutor.execute_sql` (`infrastructure/sandbox/secure_code_executor.py` dòng 426–437):
     Chỉ tạo `TABLE` vật lý cho lần đầu tiên gặp một `parquet_path`, các alias tiếp theo trỏ cùng `parquet_path` thì dùng `CREATE OR REPLACE VIEW`:
     ```python
            # 3. Register authorized parquet tables (materialize once per file, alias via VIEW)
            primary_table_by_path: Dict[str, str] = {}
            for table_name, parquet_path in table_parquet_mapping.items():
                if not os.path.exists(parquet_path):
                    logger.warning("Parquet file not found: %s", parquet_path)
                    return False, None, f"Tệp dữ liệu bảng '{table_name}' không tồn tại: {parquet_path}"

                safe_path = os.path.abspath(parquet_path).replace("\\", "/").replace("'", "''")
                escaped_tname = str(table_name).replace('"', '""')
                if safe_path not in primary_table_by_path:
                    con.execute(
                        f'CREATE OR REPLACE TABLE "{escaped_tname}" AS SELECT * FROM read_parquet(\'{safe_path}\')'
                    )
                    primary_table_by_path[safe_path] = escaped_tname
                else:
                    primary_tname = primary_table_by_path[safe_path]
                    if escaped_tname != primary_tname:
                        con.execute(
                            f'CREATE OR REPLACE VIEW "{escaped_tname}" AS SELECT * FROM "{primary_tname}"'
                        )
     ```

---

### 🔴 Lỗi 4: Lỗi logic Trigger 2 (0 dòng kết quả) trong `TabularExecutor._are_all_filter_values_verified`
- **File:** `application/services/tabular_executor.py` (dòng 414–433)
- **Hiện trạng lỗi:**
  ```python
  def _are_all_filter_values_verified(
      self,
      code: str,
      entity_links: List[EntityLinkResult],
  ) -> bool:
      if not entity_links:
          return True
  ```
  - Nếu `entity_links` rỗng `[]` nhưng câu lệnh SQL của LLM lại có mệnh đề `WHERE` lọc theo chuỗi ký tự do LLM tự suy đoán (ví dụ `WHERE chi_nhanh = 'Ha Noi'` chưa chuẩn hóa dấu), hàm trả về `True` ("đã xác thực") và **bỏ qua luôn vòng lặp tự sửa lỗi (Trigger 2)** ngay ở lần thử đầu tiên!
  - Hoặc khi `entity_links` có kết quả đã xác thực (`el.value = 'Hà Nội'`), nhưng trong `code` mà LLM sinh ra lại không dùng `el.value` đó mà viết một giá trị khác, hàm vẫn trả về `True`.

- **Cách sửa chuẩn tại `application/services/tabular_executor.py` (dòng 414–433):**
  ```python
    def _are_all_filter_values_verified(
        self,
        code: str,
        entity_links: List[EntityLinkResult],
    ) -> bool:
        """
        Trigger 2 verification: Checks if filter conditions in query
        correspond to verified entity links.
        """
        if not entity_links:
            # If there are string literal comparisons in a WHERE clause without any entity link verification,
            # treat as unverified so Self-Correction can suggest actual distinct values.
            if re.search(r"\bWHERE\b.*(=|LIKE|ILIKE|IN)\s*\(?['\"]", code, re.IGNORECASE | re.DOTALL):
                return False
            return True

        # Check unlinked entities
        unlinked = [el for el in entity_links if el.method == "unlinked" or el.score < 0.7]
        if unlinked:
            return False

        # Ensure linked canonical values are actually present in the generated code
        for el in entity_links:
            if el.value and el.value not in code:
                return False

        return True
  ```

---

## Nhóm 2: Lỗi Lệch Key Dữ Liệu & Phân Quyền RBAC (Medium Severity)

### 🟡 Lỗi 5: Lệch key giữa `chat.py` với `Router` và `HybridEngine`, lọc Few-Shot trước khi chọn bảng
- **File:** `api/routes/chat.py` (dòng 163–185, 234–276, 368–386)
- **Hiện trạng lỗi:**
  1. **Lệch key `business_keywords` vs `keywords`:**
     Tại `api/routes/chat.py` (dòng 168), dict bảng dùng key `"keywords": t.business_keywords or []`, trong khi `Router.select_top_tables` (`application/services/router.py` dòng 333) lại đọc `table.get("business_keywords", [])`. Hệ quả là danh sách từ khóa nghiệp vụ luôn bị rỗng `[]` khi chấm điểm chọn bảng.
  2. **Thiếu `file_name`, `sheet_name`, `table_alias` trong `candidate_tables`:**
     Tại `api/routes/chat.py` (dòng 163–170), mỗi phần tử của `candidate_tables` chỉ có `"table_name": t.sheet_name` mà không có `"file_name"` và `"sheet_name"`. Khi vào nhánh `HYBRID`, `HybridEngine.execute_hybrid` (`application/services/hybrid_engine.py` dòng 142–145) đọc `first_tbl.get("file_name")` (bằng `None`) và `first_tbl.get("sheet_name")` (bằng `None`), khiến dòng nguồn bị hiển thị sai thành `📊 Nguồn dữ liệu: File [Tên_Sheet] - Sheet [Sheet1]`.
  3. **Lọc Few-Shot trước khi biết bảng đích:**
     Tại `api/routes/chat.py` (dòng 234–238), `target_table_ids` đang lấy từ toàn bộ `candidate_tables` của phòng ban thay vì ưu tiên `routing_result.candidate_table_ids`. Nếu phòng ban có nhiều bảng, Few-Shot của bảng khác có thể chiếm chỗ Top 3 của bảng đang được hỏi.
  4. **Nhánh `HYBRID` tại `api/routes/chat.py` (dòng 368–386):**
     Chưa lọc `target_tables` theo `routing_result.candidate_table_ids` như nhánh `TABULAR`, và chưa gán `debug_info.language = hybrid_res.debug.language` khi trả về.

- **Cách sửa chuẩn tại `api/routes/chat.py`:**
  1. Khi khởi tạo `candidate_tables` (dòng 163–185), bổ sung đầy đủ các key:
     ```python
     candidate_tables: List[Dict[str, Any]] = [
         {
             "id": t.id,
             "table_name": t.sheet_name,
             "sheet_name": t.sheet_name,
             "file_name": t.file.file_name if t.file else "BaoCao.xlsx",
             "description": t.table_description or "",
             "keywords": t.business_keywords or [],
             "business_keywords": t.business_keywords or [],
             "parquet_path": t.parquet_path,
             ...
     ```
  2. Khi lọc `fewshot_query` (dòng 234–238), ưu tiên lọc theo `routing_result.candidate_table_ids`:
     ```python
     target_table_ids = (
         routing_result.candidate_table_ids
         if routing_result.candidate_table_ids
         else [t.get("id") for t in candidate_tables if t.get("id")]
     )
     ```
  3. Tại nhánh `elif route == "HYBRID":` (dòng 368–386), lọc `target_tables` theo `routing_result.candidate_table_ids` (giống dòng 279–283 của `TABULAR`), truyền `candidate_tables=target_tables`, và cập nhật `debug_info`:
     ```python
     elif route == "HYBRID":
         target_tables = candidate_tables
         if routing_result.candidate_table_ids:
             target_tables = [
                 t for t in candidate_tables if t.get("id") in routing_result.candidate_table_ids
             ] or candidate_tables
         entity_links = await entity_linker_svc.link_entities(
             query=rewritten_query,
             candidate_tables=target_tables,
         )
         hybrid_res = await hybrid_svc.execute_hybrid(
             query=rewritten_query,
             department_id=auth.department_id,
             user_id=auth.user_id,
             is_admin=auth.is_admin,
             sub_questions=routing_result.sub_questions,
             candidate_tables=target_tables,
             fewshot_examples=fewshot_dicts,
             entity_links=entity_links,
         )
         answer_markdown = hybrid_res.answer_markdown
         sources = hybrid_res.sources
         tables = hybrid_res.tables
         if hybrid_res.debug:
             debug_info.language = hybrid_res.debug.language
     ```

---

### 🟡 Lỗi 6: Không nhất quán quyền `is_admin` và cờ `is_public_only` giữa PostgreSQL và Qdrant
- **File liên quan:**
  - `api/routes/chat.py` (dòng 151–162, 187–198, 357–382)
  - `application/services/rag_engine.py` (dòng 91–97, 123–131)
  - `application/services/hybrid_engine.py` (dòng 76–86, 175–180, 209–214)
  - `infrastructure/vector_store/qdrant_store.py` (dòng 143–169)
- **Hiện trạng lỗi:**
  1. Trong `api/routes/chat.py` (dòng 154 và 190): Khi lọc `TableCatalogModel` và `DocumentModel` trong PostgreSQL, nếu `not req.is_public_only`, hệ thống luôn áp bộ lọc `department_id / is_public / owner_user_id` mà quên kiểm tra `if not auth.is_admin:`. Do đó, Admin không nhìn thấy bảng tính/tài liệu của phòng ban khác trong Router & Tabular Engine (mặc dù Qdrant ở `qdrant_store.py` dòng 159 lại cho phép `is_admin` xem toàn bộ).
  2. Ngược lại, khi người dùng gửi `req.is_public_only = True` vào `POST /chat`, PostgreSQL chỉ lấy dữ liệu `is_public == True`, nhưng `rag_svc.answer_query`, `hybrid_svc.execute_hybrid` và `vector_store.hybrid_search` chưa hỗ trợ tham số `is_public_only: bool = False`, dẫn đến Qdrant vẫn trả về các tài liệu nội bộ phòng ban!

- **Cách sửa chuẩn:**
  1. Trong `api/routes/chat.py` (dòng 152–161 và 188–197):
     ```python
     if req.is_public_only:
         table_query = table_query.filter(TableCatalogModel.is_public == True)
     elif not auth.is_admin:
         table_query = table_query.filter(
             or_(
                 TableCatalogModel.department_id == auth.department_id,
                 TableCatalogModel.is_public == True,
                 TableCatalogModel.owner_user_id == auth.user_id,
             )
         )
     ```
     (Làm tương tự cho `doc_query` ở dòng 188–197).
  2. Trong `QdrantVectorStore.hybrid_search` (`infrastructure/vector_store/qdrant_store.py` dòng 143–168), `VectorStore.hybrid_search` (`application/interfaces/vector_store.py`), `RAGEngine.answer_query` (`application/services/rag_engine.py`), và `HybridEngine.execute_hybrid` (`application/services/hybrid_engine.py`):
     Thêm tham số tùy chọn `is_public_only: bool = False`. Trong `QdrantVectorStore.hybrid_search`:
     ```python
        if is_public_only:
            rbac_filter = models.Filter(
                must=[models.FieldCondition(key="is_public", match=models.MatchValue(value=True))]
            )
        elif is_admin:
            rbac_filter = None
        else:
            rbac_filter = models.Filter(
                should=[
                    models.FieldCondition(key="department_id", match=models.MatchValue(value=department_id)),
                    models.FieldCondition(key="is_public", match=models.MatchValue(value=True)),
                    models.FieldCondition(key="owner_user_id", match=models.MatchValue(value=user_id)),
                ]
            )
     ```
     Và truyền `is_public_only=req.is_public_only` từ `chat.py` xuống `rag_svc.answer_query` và `hybrid_svc.execute_hybrid`.

---

### 🟡 Lỗi 7: Lỗ hổng RBAC, thiếu kiểm tra AST cho `suggested_sql`, gán nhầm bảng và thiếu Embedding trong `feedback.py`
- **File:** `api/routes/feedback.py` (dòng 42–116)
- **Hiện trạng lỗi:**
  1. **Thiếu kiểm tra quyền sở hữu tin nhắn:** `POST /feedback` truy vấn `ChatMessageModel` theo `req.message_id` nhưng không kiểm tra xem `chat_msg.session.user_id` có thuộc về `auth.user_id` (hoặc `auth.is_admin`) hay không.
  2. **Không kiểm tra an toàn SQL đối với `req.suggested_sql`:** Nếu người dùng truyền `suggested_sql` độc hại hoặc sai cú pháp, hệ thống lưu thẳng vào `FewShotExampleModel` với `source="verified"` mà không gọi `validate_duckdb_sql`.
  3. **Gán nhầm bảng & không lọc RBAC khi tìm bảng (dòng 82–92):**
     - Tìm bảng theo `TableCatalogModel.sheet_name == t_name` mà không lọc theo quyền RBAC hoặc `file_name`.
     - Nguy hiểm hơn, dòng 88–92 có fallback `any_table = db.query(TableCatalogModel).first()` — nếu tin nhắn không có bảng cụ thể, nó lấy đại bảng đầu tiên trong DB (kể cả của phòng ban khác) để gắn câu SQL vào!
  4. **Thiếu vector `embedding` khi lưu `FewShotExampleModel` (dòng 103–113):**
     Bản ghi `FewShotExampleModel` được tạo với `embedding=None`, khiến việc tính `cosine_similarity` ở `chat.py` không hoạt động cho các câu `verified`.

- **Cách sửa chuẩn tại `api/routes/feedback.py`:**
  1. Kiểm tra quyền sở hữu phiên chat sau dòng 60:
     ```python
     if chat_msg.session and not auth.is_admin and chat_msg.session.user_id != auth.user_id:
         raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN,
             detail="Truy cập bị từ chối: Bạn không có quyền đánh giá tin nhắn của người dùng khác."
         )
     ```
  2. Kiểm tra `validate_duckdb_sql(sql_to_save.strip())` trước khi lưu vào `FewShotExampleModel`.
  3. Khi tìm `table_id` (dòng 75–93):
     - Lọc `TableCatalogModel` theo phạm vi RBAC của user (`department_id == auth.department_id` hoặc `is_public == True` hoặc `owner_user_id == auth.user_id`).
     - Chỉ cho phép fallback sang bảng đầu tiên trong phạm vi RBAC nếu `chat_msg.route in ("TABULAR", "HYBRID")` (không gán bừa cho tin nhắn `DOCUMENT` hay `CHITCHAT`).
  4. Inject `embedder: Embedder = Depends(get_embedder)` vào `submit_feedback` và sinh `embedding` cho `question` trước khi lưu `FewShotExampleModel`:
     ```python
     emb_vec = None
     if embedder:
         try:
             emb_res = embedder.embed_query(question)
             emb_vec = emb_res.get("dense") if isinstance(emb_res, dict) else emb_res
         except Exception:
             emb_vec = None
     ```

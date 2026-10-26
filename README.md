# Enterprise RAG & Tabular Execution Harness

Hệ thống Trợ lý AI Hỏi đáp Dữ liệu Doanh nghiệp (Enterprise RAG & Tabular Execution Harness) đạt chuẩn **Clean Architecture**, hoạt động **100% Offline (Air-gapped LAN)**, **không phụ thuộc Docker** (triển khai native hoàn toàn trên Windows Server 2022 và Ubuntu 22.04).

Hệ thống cho phép người dùng tại nhiều phòng ban đồng thời tải lên và truy vấn dữ liệu bảng tính (`.xlsx`, `.xls`) kết hợp văn bản (`.pdf`, `.docx`, `.doc`, `.md`, `.txt`) với cơ chế phân quyền RBAC đa cấp độ, sandbox thực thi mã an toàn, và kiểm tra trích dẫn nguồn nghiêm ngặt.

---

## 1. Kiến trúc Hệ thống (Clean Architecture)

Hệ thống tuân thủ nghiêm ngặt nguyên tắc **Clean Architecture** (Dependency Inversion Principle), các tầng bên trong độc lập hoàn toàn với framework và thư viện bên ngoài:

```
RAG_chatbot/
├── api/                        # Interface Adapters: FastAPI HTTP Routes & Dependencies
│   ├── dependencies/
│   │   ├── auth.py             # ADSSO Header Authentication (X-User-Id, X-Department-Id, ...)
│   │   └── services.py         # Dependency Injection Providers / Factories
│   ├── routes/
│   │   ├── upload.py           # POST /upload, GET /upload/{job_id}, DELETE /files/{file_id}
│   │   ├── chat.py             # POST /chat (Multi-turn, Routing, Dispatch, RBAC Debug Filter)
│   │   └── feedback.py         # POST /feedback (User thumbs up/down, Few-Shot auto-promotion)
│   └── main.py                 # FastAPI Application Lifespan & CORS Configuration
│
├── application/                # Use Cases & Application Business Logic
│   ├── interfaces/             # Abstract Base Classes (Contracts)
│   │   ├── llm_client.py       # LLMClient interface
│   │   ├── vector_store.py     # VectorStore interface (Qdrant native / embedded)
│   │   ├── embedder.py         # Embedder interface (Dense BGE-M3 + BM25 Sparse)
│   │   ├── reranker.py         # Reranker interface (BAAI/bge-reranker-v2-m3)
│   │   └── code_executor.py    # Sandboxed execution interface
│   ├── prompts/
│   │   └── prompts.py          # Tập trung toàn bộ System Prompts chuẩn hóa
│   └── services/
│       ├── excel_preprocessor.py # Xử lý ô gộp, header nhiều tầng, làm sạch số/ngày VN
│       ├── catalog_service.py    # Trích xuất metadata, từ khóa, sinh synthetic few-shot
│       ├── doc_ingestor.py       # Docling parser, phân loại Scan/Digital PDF, chunking
│       ├── router.py             # Viết lại câu hỏi nhiều lượt, phân loại 6 Intent
│       ├── entity_linker.py      # Entity linking kết hợp từ điển đồng nghĩa & fuzzy
│       ├── tabular_executor.py   # Sandbox AST/DuckDB/Pandas & 3-Trigger Self-Correction
│       ├── rag_engine.py         # Qdrant Hybrid RRF Search + BGE Reranker + Citation Audit
│       ├── hybrid_engine.py      # Song song Tabular + Document & LLM Synthesis
│       └── output_formatter.py   # Định dạng bảng VN, tóm tắt điều hành, chỉ mục nguồn [n]
│
├── domain/                     # Enterprise Business Entities & Rules
│   └── entities/
│       ├── query_intent.py     # QueryIntent, SubQuestion
│       ├── citation.py         # SourceCitation, CitationAuditResult
│       └── tabular_result.py   # ExecutionResult, TableMetadata
│
├── infrastructure/             # Frameworks & Drivers: DB, Models, Sandbox
│   ├── database/
│   │   ├── models.py           # 14 SQLAlchemy Models (PostgreSQL 16 & SQLite fallback)
│   │   └── session.py          # SessionLocal, connection pooling, health checks
│   ├── vector_store/
│   │   └── qdrant_store.py     # Qdrant Client (Hybrid Dense 1024 + Sparse BM25 + RBAC payload filter)
│   ├── ml_models/
│   │   ├── bge_embedder.py     # Local BGE-M3 Loader & inference
│   │   └── bge_reranker.py     # Local BGE-Reranker-v2-m3 Loader & inference
│   ├── sandbox/
│   │   └── secure_executor.py  # AST Whitelist/Blacklist, RestrictedProcessPool, 15s timeout
│   └── ocr/
│       └── rapid_ocr.py        # RapidOCR local offline engine
│
├── config.py                   # Pydantic BaseSettings, cấu hình offline toàn diện
├── requirements.txt            # Phiên bản thư viện cố định (Pinned versions)
├── scripts/                    # Scripts cài đặt và tự động hóa
│   ├── download_models.py      # Tải offline model weights (BGE-M3, Reranker, OCR)
│   ├── setup_qdrant_service.ps1# Script tự động kích hoạt binary Qdrant cho Windows
│   ├── init_db.py              # Script tạo bảng và kiểm tra kết nối CSDL
│   └── schema.sql              # PostgreSQL 16 DDL Script
├── docs/
│   └── native_setup_guide.md   # Hướng dẫn chi tiết triển khai Native không dùng Docker
└── tests/                      # Bộ kiểm thử 64 tests toàn diện (100% Passed)
    ├── test_llm_client.py
    ├── test_excel_preprocessor.py
    ├── test_doc_ingestor.py
    ├── test_router_and_entity_linker.py
    ├── test_tabular_executor.py
    ├── test_rag_and_hybrid_engine.py
    └── test_api.py
```

---

## 2. Thông số Môi trường & Phần cứng

| Thành phần | Đặc tả triển khai |
| :--- | :--- |
| **Môi trường** | 100% Offline (Air-gapped LAN), Không Docker. Cài đặt Native Services. |
| **Hệ điều hành** | Windows Server 2022 / Windows 11 / Ubuntu 22.04 LTS. |
| **Phần cứng mục tiêu** | Intel Core i7-14700, 16GB RAM, GPU NVIDIA RTX A400 (4GB VRAM). |
| **Máy chủ Testbed Colab** | Tesla T4 GPU (15GB VRAM), Python 3.13, Ubuntu. |
| **Ngôn ngữ** | Python 3.11 / 3.13 64-bit. |
| **Metadata Database** | PostgreSQL 16 Native (Kèm tương thích SQLite in-memory cho offline unit test). |
| **Vector Database** | Qdrant Native Binary (Port 6333, Qdrant-Client gRPC/HTTP). |
| **Mô hình Ngôn ngữ** | `gpt-oss-120b` (hoặc vLLM/Ollama OpenAI-compatible, 200k context). |
| **Embedding & Reranker** | `BAAI/bge-m3` (Dense 1024-dim + Sparse BM25), `BAAI/bge-reranker-v2-m3`. |
| **Múi giờ & Định dạng** | GMT+7 (`Asia/Ho_Chi_Minh`), Số VN: `1.234.567`, Ngày VN: `dd/mm/yyyy`. |

---

## 3. Các Tính năng Cốt lõi Hoàn thành

### Module 1: Unified Ingestion Pipeline
- **Xử lý Bảng tính Excel thông minh (`ExcelPreprocessor`)**:
  - Tự động điền giá trị cho toàn bộ ô trong vùng gộp (`merged_cells`) cả chiều dọc và chiều ngang.
  - Tự động phát hiện và ghép cấu trúc header 2 tầng (`"Cha - Con"`).
  - Chuẩn hóa tên cột: sinh `column_alias` dạng snake_case không dấu cho SQL, giữ nguyên tên hiển thị.
  - Phân tích số tiếng Việt (phân cách hàng nghìn bằng dấu chấm `.`, thập phân dấu phẩy `,`, dấu phần trăm `%`), chuyển đổi chuỗi ngày và Excel serial dates.
  - Tách và loại bỏ dòng tổng cộng/dòng ghi chú tổng kết (`summary rows`) trước khi xuất Parquet.
  - Tự động lưu bảng tính vào định dạng chuẩn Apache Parquet theo đường dẫn phân cấp phòng ban.
- **Danh mục Siêu dữ liệu & Few-Shot Tự động (`CatalogService`)**:
  - Tự động sinh mô tả nghiệp vụ và từ khóa tìm kiếm (`business_keywords`) cho từng bảng.
  - Tự sinh 3-5 cặp câu hỏi - câu lệnh SQL mẫu (`synthetic few-shot`), chạy thử nghiệm trên DuckDB sandbox để thẩm định trước khi ghi vào CSDL.
- **Trích xuất Văn bản Đa định dạng (`DocumentIngestor`)**:
  - Hỗ trợ `.pdf`, `.docx`, `.doc`, `.md`, `.txt`.
  - Phân loại tài liệu số hóa (digital) và tài liệu quét (scanned), tự động kích hoạt RapidOCR offline khi phát hiện trang quét ảnh.
  - Cắt phân đoạn thông minh (`hierarchical chunking`) bảo toàn đường dẫn ngữ cảnh (`Breadcrumbs: Chương > Mục > Tiểu mục`).
  - Xử lý bảng trong văn bản: tự động lặp lại header cho mọi chunk bị tràn trang.

### Module 2: Query Router & Entity Linker
- **Viết lại câu hỏi ngữ cảnh (`rewrite_query`)**: Khôi phục chủ ngữ, đại từ, liên kết thông tin từ $N=6$ lượt trò chuyện trước đó.
- **Phân loại 6 Luồng Ý định (`route_query`)**:
  1. `TABULAR`: Dành riêng cho câu hỏi tra cứu, tính toán số liệu trên bảng tính.
  2. `DOCUMENT`: Dành cho câu hỏi tra cứu chính sách, quy chế, văn bản pháp quy.
  3. `HYBRID`: Câu hỏi kết hợp (ví dụ: đối chiếu số liệu bảng tính với định mức chính sách).
  4. `CLARIFY`: Tự động hỏi lại khi thông tin quá mơ hồ hoặc thiếu tiêu chí lọc trọng yếu.
  5. `CHITCHAT`: Trả lời lịch sự các câu chào hỏi xã giao.
  6. `OUT_OF_SCOPE`: Từ chối trả lời câu hỏi ngoài phạm vi dữ liệu nội bộ.
- **Entity Linker Đa tầng**: Chuẩn hóa từ viết tắt phòng ban/sản phẩm (Tier 2), đối chiếu bảng/cột qua từ điển và Levenshtein fuzzy ratio, sử dụng LLM phân giải khi có sự nhập nhằng.

### Module 3: Execution Engines & Self-Correction
- **Tabular Engine Sandbox An toàn Tuyệt đối**:
  - Cơ chế kép: Ưu tiên biên dịch SQL chạy trên **DuckDB** in-process; nếu bài toán yêu cầu thuật toán chuỗi thời gian phức tạp sẽ chuyển sang **Pandas Script**.
  - Kiểm duyệt AST Python: Cấm `eval`, `exec`, `__import__`, truy cập biến hệ thống `__builtins__`, cấm import các thư viện nguy hiểm (`os`, `sys`, `subprocess`, `socket`, `shutil`).
  - Chống SQL Injection trên DuckDB: Cấm lệnh đa phát biểu (`;`), cấm từ khóa DDL/DML (`ATTACH`, `COPY`, `INSTALL`, `PRAGMA`, `EXPORT`, `DROP`).
  - Sandbox thực thi trong tiến trình cô lập (`RestrictedProcessPoolExecutor`) với giới hạn 15 giây và 1024MB RAM.
  - Cơ chế **Tự Sửa Lỗi (Self-Correction)** kích hoạt theo 3 trường hợp:
    1. Khi phát sinh ngoại lệ cú pháp/kiểu dữ liệu.
    2. Khi kết quả trả về 0 dòng trên bảng đã xác thực.
    3. Khi kết quả trả về toàn `NULL`/`NaN` ở cột mục tiêu.
    - Tự động dừng sớm nếu code sinh mới trùng lặp với code cũ.
- **Document RAG Engine Lai (Hybrid Vector Search)**:
  - Qdrant Search: Kết hợp song song Dense Vector (1024 chiều) và Sparse Vector (BM25) qua thuật toán **Reciprocal Rank Fusion (RRF)**.
  - Phân quyền RBAC trực tiếp trong truy vấn Vector: `(department_id == X) OR (is_public == true) OR (owner_user_id == U)`.
  - Tái xếp hạng ngữ nghĩa qua `BAAI/bge-reranker-v2-m3`. Tự động từ chối nếu điểm tin cậy < ngưỡng cấu hình.
- **Hybrid Multi-Engine**:
  - Tách câu hỏi thành các `sub_questions`.
  - Chạy song song Tabular và Document RAG qua `asyncio.gather`.
  - Hợp nhất câu trả lời mạch lạc, áp dụng cơ chế suy thoái mềm (graceful degradation) nếu một nhánh không có dữ liệu.

### Module 4: Output Formatter & Citation Enforcer
- **Hiển thị Bảng số liệu**:
  - Mã nguồn tự động format bảng Markdown (phân cách hàng nghìn bằng `.`, ngày `dd/mm/yyyy`).
  - Bảng > 50 dòng: Hiển thị 20 dòng đầu kèm thống kê tóm tắt (Tổng số dòng, Min, Max, Sum do code tính).
  - LLM chỉ đóng vai trò viết nhận xét tóm tắt điều hành 2-4 câu phía trên bảng.
  - Dòng nguồn: `📊 Nguồn dữ liệu: File [Tên_File.xlsx] - Sheet [Tên_Sheet]`.
- **Kiểm soát Trích dẫn Văn bản (Citation Enforcer)**:
  - Mọi luận điểm trích dẫn bắt buộc gắn chỉ số `[n]`.
  - Tự động sinh mục **📚 Chỉ mục nguồn trích dẫn (References)**: `[n] File.pdf | Trang X | Mục Y — "Trích đoạn nguyên văn..."`.
  - Hậu kiểm soát trích dẫn (`CitationAuditor`): Kiểm tra fuzzy ratio $\ge 90\%$ với chunk gốc trong CSDL; tự động loại bỏ các trích dẫn ảo (hallucinated citations).
- **Admin-Only Debug Diagnostics Filter**:
  - Thông tin debug (truy vấn SQL/Python, số lần retry, latency) chỉ gửi về khi người dùng mang vai trò `admin`. Người dùng thông thường luôn nhận `debug: null`.

---

## 4. Hướng dẫn Triển khai & Vận hành

### Bước 1: Thiết lập Môi trường & Thư viện (Air-Gapped)
1. Cài đặt Python 3.11 64-bit trên máy chủ nội bộ.
2. Sao chép các gói offline wheels và cài đặt:
   ```bash
   pip install --no-index --find-links=./offline_wheels -r requirements.txt
   ```
3. Cấu hình file `.env` từ file mẫu:
   ```bash
   cp .env.example .env
   ```

### Bước 2: Khởi động Dịch vụ Native CSDL & Qdrant
1. **PostgreSQL 16**: Tạo database và chạy script khởi tạo:
   ```bash
   python scripts/init_db.py
   ```
2. **Qdrant Vector DB**:
   - Trên Windows: Chạy `scripts\setup_qdrant_service.ps1` hoặc chạy trực tiếp `qdrant.exe`.
   - Trên Ubuntu: Kích hoạt dịch vụ `sudo systemctl start qdrant`.
   - Kiểm tra kết nối: `curl http://localhost:6333/healthz`.

### Bước 3: Chạy Bộ Kiểm thử Toàn diện (64 Tests)
```bash
pytest tests/ -v
```
Toàn bộ 64 test cases về xác thực ADSSO, RBAC, Excel preprocessing, Vector search, Sandbox, Routing, RAG Engine, API endpoints sẽ chạy thành công trong vòng dưới 10 giây.

### Bước 4: Khởi chạy Ứng dụng Sản xuất (Production Native Uvicorn)
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Giao diện tương tác Swagger UI: `http://localhost:8000/docs`

---

## 5. Danh mục API Endpoints

| Phương thức | Đường dẫn | Chức năng | Phân quyền RBAC |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Kiểm tra tình trạng CSDL PostgreSQL và Qdrant | Công khai |
| `POST` | `/upload` | Tải lên tệp Excel/Văn bản, kiểm tra SHA256, chạy Ingestion ngầm | Tất cả User có header ADSSO |
| `GET` | `/upload/{job_id}` | Kiểm tra tiến độ và trạng thái Ingestion | Tất cả User |
| `DELETE` | `/files/{file_id}` | Xóa tệp vật lý, bảng Parquet, Qdrant vectors và CSDL | Chỉ Owner hoặc Admin |
| `POST` | `/chat` | Endpoint hội thoại thông minh đa lượt, đa động cơ | Tất cả User (debug chỉ trả về cho Admin) |
| `POST` | `/feedback` | Ghi nhận đánh giá 👍/👎, tự động thăng cấp SQL lên Few-Shot | Tất cả User |

---

## 6. Tiêu chuẩn Header ADSSO (Reverse Proxy)

Hệ thống nhận diện người dùng thông qua các HTTP Headers do Reverse Proxy (Nginx/Traefik) nội bộ đính kèm:
- `X-User-Id`: Mã định danh người dùng (ví dụ: `nv_nguyenvana`).
- `X-Department-Id`: Mã phòng ban (ví dụ: `DEP_FINANCE`, `DEP_IT`, `DEP_SALES`).
- `X-User-Role`: Vai trò hệ thống (`user` hoặc `admin`).
- `X-User-Name`: Họ và tên hiển thị tiếng Việt.

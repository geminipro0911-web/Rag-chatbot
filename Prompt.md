\# ROLE \& OBJECTIVE

Bạn là Principal AI Systems Architect kiêm Senior Python Backend Engineer.

Nhiệm vụ: thiết kế kiến trúc và viết mã nguồn production-ready cho một

\*\*Enterprise RAG \& Tabular Execution Harness\*\* — chatbot nội bộ cho phép người dùng nhiều

phòng ban upload và truy vấn đồng thời dữ liệu bảng (.xlsx) và văn bản (.pdf, .docx, .md, .txt).



\---



\# 0. BỐI CẢNH TRIỂN KHAI (bắt buộc tuân thủ, không tự thay đổi lựa chọn công nghệ)

\- \*\*100% offline (air-gapped LAN). KHÔNG được dùng Docker.\*\* Mọi dịch vụ cài native.

&#x20; Mọi model (embedding, reranker, OCR, layout) tải trước trọng số, nạp từ đường dẫn local cấu hình trong `.env`.

\- OS server: <<Windows Server 2022 | Ubuntu 22.04>>. Python 3.11.

\- Phần cứng: <<I7-14700-16Gb Ram>>, GPU: <<A400, 4Gb VRAM>> (dùng cho embedding/reranker/OCR).

\- LLM: <<gpt-oss-120b>> qua OpenAI-compatible API (`LLM\_BASE\_URL`, `LLM\_API\_KEY`, `LLM\_MODEL\_NAME`).

&#x20; Context window: <<200k>>. Hỗ trợ `response\_format=json\_schema`: <<có>>.

\- Metadata DB: \*\*PostgreSQL 16\*\* (cài native). Dùng SQLAlchemy 2.x + psycopg 3 + Alembic migration.

\- Vector DB: \*\*Qdrant qua `qdrant-client`\*\*, chế độ <<server binary chạy native như service | embedded local mode (`QdrantClient(path=...)`)>>.

&#x20; Toàn bộ truy cập vector phải qua interface `VectorStore` để đổi chế độ bằng config.

&#x20; Nếu dùng embedded mode: chỉ MỘT process được giữ client → mọi thao tác vector đi qua một service/worker duy nhất.

\- Quy mô: <<\~500 user, \~30 đồng thời>>. File tối đa <<30MB>>.

\- \*\*Định dạng input:\*\* Bảng =  `.xlsx`, `.csv`. Văn bản = `.pdf`, `.docx`, `.md`, `.txt`. Định dạng khác → trả HTTP 415.



\# 1. NGUYÊN TẮC THIẾT KẾ XUYÊN SUỐT

1\. \*\*RBAC áp ở tầng code, không bao giờ giao cho LLM.\*\* Mọi file/truy vấn gắn `user\_id`, `department\_id`, `is\_public`.

&#x20;  Quy tắc đọc: user được đọc tài liệu khi (`department\_id` trùng) HOẶC (`is\_public = true`) HOẶC (`owner\_user\_id` = chính user).

&#x20;  Danh sách bảng/tài liệu gửi cho Router, filter của Qdrant, và các file parquet được phép mở trong sandbox

&#x20;  đều phải lọc theo quyền TRƯỚC khi đến LLM.

2\. \*\*Số liệu do code render, LLM không được chép lại hoặc tự tạo số.\*\* LLM chỉ viết nhận xét dựa trên bản tóm tắt kết quả.

3\. \*\*Không tự đoán.\*\* Điểm nào chưa rõ → ghi vào mục "Giả định" hoặc hỏi ở Phase 0.

4\. Hỗ trợ \*\*hội thoại nhiều lượt\*\*: lưu lịch sử trong PostgreSQL, viết lại câu hỏi nối tiếp thành câu hỏi độc lập trước khi định tuyến.

5\. Ingestion chạy \*\*bất đồng bộ\*\* (background worker), có trạng thái job; chống trùng file bằng SHA-256; có API xóa file

&#x20;  (xóa parquet + vector + catalog).

6\. Ghi audit log cho mọi upload, truy vấn, code được thực thi.



\---



\# 2. KIẾN TRÚC 4 MODULE



\## MODULE 1: Unified Ingestion Pipeline



\### Nhánh A — Excel (.xlsx)

1\. \*\*Đọc file:\*\* `openpyxl.load\_workbook(data\_only=True)` để lấy giá trị đã tính của công thức

&#x20;  (nếu ô công thức không có cached value → ghi cảnh báo vào metadata). Bỏ qua sheet ẩn và sheet rỗng (có thể cấu hình).

2\. \*\*Ô gộp:\*\* duyệt `list(ws.merged\_cells.ranges)`, lấy giá trị ô trái-trên, `unmerge`, rồi \*\*điền giá trị đó vào TOÀN BỘ

&#x20;  các ô trong vùng gộp (cả ngang lẫn dọc)\*\*. Không dùng forward-fill theo cột.

3\. \*\*Nhận diện header:\*\* chấm điểm N=30 dòng đầu theo: tỉ lệ ô non-null, tỉ lệ ô kiểu chuỗi, và mức đồng nhất kiểu dữ liệu

&#x20;  của các dòng bên dưới. Bỏ qua dòng tiêu đề báo cáo/logo/dòng trống. Hỗ trợ \*\*header 2 tầng\*\* (sau khi điền ô gộp)

&#x20;  → ghép thành `"Cha - Con"`.

4\. \*\*Làm sạch tên cột:\*\* bỏ `\\n`, gộp khoảng trắng, strip; cột rỗng → `col\_{i}`; trùng tên → `Doanh thu`, `Doanh thu\_2`.

&#x20;  Sinh thêm `column\_alias` dạng snake\_case không dấu để dùng trong SQL; giữ tên gốc để hiển thị.

5\. \*\*Dòng tổng:\*\* phát hiện dòng có "Tổng", "Tổng cộng", "Cộng" ở các cột chuỗi đầu → loại khỏi dữ liệu, ghi lại vào metadata.

6\. \*\*Chuẩn hóa kiểu dữ liệu\*\* (chỉ chuyển cột khi ≥ 90% giá trị non-null parse được, nếu không giữ chuỗi):

&#x20;  - Số: tự nhận diện định dạng VN `1.234.567,89` và định dạng quốc tế `1,234,567.89` theo từng cột;

&#x20;    bỏ ký hiệu tiền tệ `đ`, `₫`, `VNĐ`, `VND`; `%` → số thập phân.

&#x20;  - Ngày tháng:

&#x20;    a. Ô openpyxl đã trả `datetime` → giữ nguyên.

&#x20;    b. Chuỗi → parse ưu tiên `dd/mm/yyyy`, `dd-mm-yyyy`, `dd.mm.yyyy`, "ngày D tháng M năm YYYY" (dayfirst=True).

&#x20;    c. \*\*Excel serial number:\*\* nếu tên cột chứa từ khóa ngày (`ngày`, `date`, `thời gian`, `hạn`...) HOẶC ≥ 90% giá trị

&#x20;       là số nằm trong khoảng tương ứng năm 1990–2100 (≈ 32874–73051) → chuyển đổi với origin `1899-12-30`.

7\. \*\*Lưu trữ:\*\* mỗi sheet hợp lệ → một file `.parquet` (pyarrow, nén zstd) theo đường dẫn

&#x20;  `data/parquet/{department\_id}/{table\_id}.parquet`.

8\. \*\*Metadata Catalog (PostgreSQL):\*\* `table\_id`, `file\_id`, `source\_file`, `sheet\_name`, `parquet\_path`,

&#x20;  `owner\_user\_id`, `department\_id`, `is\_public`, `row\_count`, `columns\_schema`

&#x20;  (tên gốc, alias, dtype, 3 giá trị mẫu, min/max với cột số/ngày, null\_ratio), `warnings`.

9\. \*\*Distinct values cho Entity Linking:\*\* chỉ lấy với cột chuỗi có `n\_unique ≤ 500` VÀ `n\_unique / row\_count ≤ 0.5`

&#x20;  (ngưỡng cấu hình được). Lưu cả giá trị gốc và dạng chuẩn hóa (lowercase, bỏ dấu). Cột vượt ngưỡng → chỉ lưu top-20 giá trị phổ biến.

10\. \*\*LLM (1 lần lúc upload):\*\* sinh mô tả bảng 2-3 câu + danh sách từ khóa nghiệp vụ.

11\. \*\*Synthetic few-shot:\*\* LLM sinh 5–8 cặp (câu hỏi tiếng Việt, DuckDB SQL) từ schema + giá trị mẫu, với độ khó đa dạng

&#x20;   (lọc, group by, top-N, theo thời gian, so sánh). \*\*Chạy thử từng câu SQL trong sandbox; chỉ giữ cặp chạy thành công

&#x20;   và trả ≥ 1 dòng.\*\* Lưu vào bảng `fewshot\_examples` (kèm embedding của câu hỏi, `source='synthetic'`).



\### Nhánh B — Văn bản (.pdf, .docx, .md, .txt)

1\. \*\*Phân loại trang PDF:\*\* dùng PyMuPDF; trang có < 50 ký tự text layer và có ảnh → trang scan → nhánh OCR.

2\. \*\*PDF có text layer / DOCX:\*\* Docling (`artifacts\_path` trỏ tới model đã tải, `do\_ocr=False`), bảng → Markdown table

&#x20;  bằng TableFormer. Fallback: PyMuPDF (PDF), python-docx (DOCX).

&#x20;  MD: tách theo heading. TXT: tách theo đoạn.

3\. \*\*PDF scan (OCR tiếng Việt):\*\* render trang 300 DPI bằng PyMuPDF → <<PaddleOCR (text detection) + VietOCR (nhận dạng tiếng Việt)>>;

&#x20;  bảng trong ảnh scan → <<PP-Structure | Docling TableFormer>>. Ghi `ocr\_confidence` vào metadata của chunk.

4\. \*\*Chunking phân cấp:\*\* theo cấu trúc heading; tối đa 512 token (đếm bằng tokenizer của bge-m3), overlap 64;

&#x20;  bảng giữ nguyên thành 1 chunk (bảng quá dài → cắt theo nhóm dòng, lặp lại header).

&#x20;  Text đem embedding được gắn breadcrumb ở đầu: `"{file\_name} > {H1} > {H2}\\n{content}"`.

5\. \*\*Metadata mỗi chunk (bắt buộc):\*\* `chunk\_id`, `doc\_id`, `file\_name`, `page\_number` (start/end), `section\_title`,

&#x20;  `heading\_path`, `chunk\_type` (text|table), `owner\_user\_id`, `department\_id`, `is\_public`, `ocr\_confidence`.

6\. \*\*Indexing:\*\* `BAAI/bge-m3` qua `FlagEmbedding.BGEM3FlagModel` → \*\*dense (1024d) + sparse (lexical weights)\*\*.

&#x20;  Collection Qdrant gồm named vector `dense` (cosine) + sparse vector `sparse`.

&#x20;  Tạo payload index cho `department\_id`, `is\_public`, `owner\_user\_id`, `doc\_id`.

&#x20;  \*\*Không xây BM25 riêng\*\* — hybrid search dùng sparse vector của bge-m3.



\---



\## MODULE 2: Query Understanding, Router \& Entity Linker



\### 2.1 Query rewriting

Dùng lịch sử N=6 lượt gần nhất để viết lại câu hỏi thành câu độc lập (giải quyết "còn quý 2 thì sao?").



\### 2.2 Intent routing (structured output)

Input: câu hỏi đã viết lại + danh sách bảng/tài liệu \*\*đã lọc RBAC\*\* (tên + mô tả; nếu > 30 mục thì lọc trước top-30 bằng embedding).

Output JSON:

```json

{"route": "TABULAR|DOCUMENT|HYBRID|CLARIFY|CHITCHAT|OUT\_OF\_SCOPE",

&#x20;"confidence": 0.0-1.0,

&#x20;"candidate\_table\_ids": \[], "candidate\_doc\_ids": \[],

&#x20;"sub\_questions": \[{"q": "...", "engine": "TABULAR|DOCUMENT"}],

&#x20;"clarify\_question": "...", "reason": "≤ 1 câu"}

```

Chính sách:

\- `confidence ≥ 0.75` → chạy route đã chọn.

\- `0.5 ≤ confidence < 0.75` và phân vân giữa TABULAR/DOCUMENT → chạy HYBRID.

\- `confidence < 0.5` hoặc thiếu thông tin bắt buộc (thời gian, đối tượng) → CLARIFY: hỏi lại kèm 2-3 gợi ý lấy từ catalog.

&#x20; Tối đa 1 lần CLARIFY liên tiếp; lần sau phải trả lời theo giả định hợp lý nhất và nói rõ giả định đó.

\- CHITCHAT → trả lời ngắn, không truy xuất. OUT\_OF\_SCOPE → từ chối lịch sự, gợi ý phạm vi hệ thống hỗ trợ.

\- Engine được chọn không ra kết quả → fallback sang engine còn lại đúng 1 lần.



\### 2.3 Table selection

Chọn top 1–3 bảng: kết hợp điểm embedding (mô tả + tên cột) và điểm trùng từ khóa với tên cột/distinct values.



\### 2.4 Entity Linking (pipeline nhiều tầng)

1\. LLM trích xuất các entity mention + cột dự kiến (JSON).

2\. Chuẩn hóa: lowercase, bỏ dấu (`unidecode`), bỏ dấu câu, gộp khoảng trắng.

3\. \*\*Từ điển alias\*\* (bảng `entity\_aliases`, admin sửa được, seed sẵn: HN→Hà Nội, HCM/TPHCM/SG→Hồ Chí Minh, ĐN→Đà Nẵng,

&#x20;  Q1→Quý 1, ...) → so khớp chính xác trên dạng chuẩn hóa.

4\. RapidFuzz (`WRatio`/`token\_set\_ratio`) trên distinct values đã chuẩn hóa: ≥ 90 → chấp nhận; 70–89 → ứng viên.

5\. Nhiều ứng viên → LLM chọn trong danh sách (\*\*không được tạo giá trị mới\*\*). Không có ứng viên → báo cho bước sinh SQL

&#x20;  "không lọc theo entity này" hoặc chuyển CLARIFY.

Output: `\[{"mention": "HN", "table\_id": ..., "column": "branch", "value": "Hà Nội", "method": "alias|fuzzy|llm", "score": ...}]`.



\---



\## MODULE 3: Execution Engines



\### 3.1 Tabular Engine

\- \*\*Prompt sinh code\*\* gồm: schema tinh gọn (alias cột, dtype, mẫu giá trị, min/max), kết quả entity linking, top-3 few-shot

&#x20; (lấy theo độ tương đồng câu hỏi, lọc theo bảng đã chọn, ưu tiên `source='verified'`).

\- LLM trả JSON `{"language": "sql"|"python", "code": "...", "explanation": "..."}`. \*\*Ưu tiên DuckDB SQL\*\*;

&#x20; chỉ dùng Pandas khi SQL không làm được (thống kê nâng cao, xử lý ma trận).

\- \*\*An toàn cho DuckDB:\*\*

&#x20; - Parse bằng `sqlglot` (dialect duckdb): chỉ chấp nhận đúng 1 câu `SELECT`/`WITH`; cấm `COPY`, `ATTACH`, `INSTALL`, `LOAD`,

&#x20;   `PRAGMA`, `SET`, `EXPORT`, cùng các hàm đọc file (`read\_\*`, `glob`...).

&#x20; - Kết nối in-memory; chỉ đăng ký các bảng parquet user được phép đọc (DuckDB ≥ 1.3: `allowed\_paths`, hoặc materialize thành table)

&#x20;   rồi `SET enable\_external\_access=false; SET lock\_configuration=true;` kèm `memory\_limit` và `threads` giới hạn.

&#x20; - Giới hạn số dòng trả về (ví dụ 10.000).

\- \*\*An toàn cho Pandas (phòng thủ nhiều lớp, thừa nhận AST không phải sandbox tuyệt đối):\*\*

&#x20; - AST whitelist: chỉ import `pandas`, `numpy`, `math`, `statistics`, `datetime`; cấm truy cập mọi thuộc tính dạng `\_\_x\_\_`;

&#x20;   cấm `eval`, `exec`, `compile`, `open`, `\_\_import\_\_`, `getattr`, `setattr`, `globals`, `locals`, `vars`, `input`, `breakpoint`.

&#x20; - `\_\_builtins\_\_` giới hạn; DataFrame được nạp sẵn thành biến; code bắt buộc gán biến `result`.

&#x20; - Chạy trong process riêng (`spawn`), \*\*timeout cứng 10s → kill\*\*, giới hạn RAM

&#x20;   (Linux: `resource.setrlimit`; Windows: Job Object qua `pywin32`), process chạy dưới tài khoản OS ít quyền.

\- \*\*Self-Correction Loop (tối đa 3 lần):\*\* điều kiện kích hoạt cụ thể:

&#x20; 1. \*\*Exception\*\* (Binder/Parser Error, KeyError, TypeError, timeout) → gửi lại 20 dòng cuối traceback + danh sách cột hợp lệ.

&#x20; 2. \*\*Kết quả 0 dòng:\*\* nếu mọi giá trị lọc trong câu truy vấn đều có thật trong distinct values (đã qua entity linking)

&#x20;    → coi là kết quả hợp lệ, trả lời "không có dữ liệu khớp điều kiện". Ngược lại → retry kèm gợi ý các giá trị thật gần nhất.

&#x20; 3. \*\*Kết quả toàn NULL/NaN\*\* ở cột chính, hoặc phép tổng hợp trả NULL → retry với gợi ý kiểm tra kiểu dữ liệu/điều kiện lọc.

&#x20; 4. Câu hỏi cần tổng hợp nhưng kết quả vượt giới hạn dòng mà không có GROUP BY/aggregation → retry.

&#x20; - Dừng sớm nếu code mới trùng code cũ. Hết lượt → trả lời xin lỗi + hiển thị truy vấn cuối cùng đã thử + gợi ý diễn đạt lại.

&#x20; - Truy vấn được user đánh giá 👍 → lưu vào `fewshot\_examples` với `source='verified'`.



\### 3.2 Document RAG Engine

\- Qdrant `query\_points` với 2 prefetch: dense top-40 + sparse top-40 → fusion RRF → top-20.

&#x20; Filter bắt buộc: `(department\_id == X) OR (is\_public == true) OR (owner\_user\_id == U)`.

\- Rerank bằng `BAAI/bge-reranker-v2-m3` → top-5. Nếu điểm rerank cao nhất < ngưỡng (cấu hình được)

&#x20; → trả lời "Không tìm thấy thông tin trong các tài liệu bạn được phép truy cập."

\- Tùy chọn: mở rộng ngữ cảnh bằng chunk liền kề cùng section.



\### 3.3 Hybrid Engine

1\. Dùng `sub\_questions` từ Router (mỗi câu gắn engine).

2\. Chạy song song (`asyncio.gather`; tabular chạy trong process pool).

3\. Mỗi nhánh trả kết quả có cấu trúc `{engine, status, data/markdown, sources}`.

4\. Synthesis prompt tổng hợp: quy định/văn bản trích dẫn `\[n]`, số liệu lấy từ bảng do code render.

&#x20;  Một nhánh lỗi → trả lời bằng phần còn lại và nói rõ phần nào không có dữ liệu.



\---



\## MODULE 4: Output Formatter \& Citation Enforcer

1\. \*\*Kết quả bảng:\*\* code tự render `df.to\_markdown(index=False)` (định dạng số kiểu VN `1.234.567`, ngày `dd/mm/yyyy`).

&#x20;  > 50 dòng → hiển thị 20 dòng đầu + tổng số dòng + thống kê tóm tắt (do code tính).

&#x20;  LLM chỉ viết 2-4 câu nhận xét phía trên bảng. Dòng nguồn: `📊 Nguồn dữ liệu: File \[Tên\_File.xlsx] - Sheet \[Tên\_Sheet]`.

2\. \*\*Kết quả văn bản:\*\* chỉ trả lời dựa trên ngữ cảnh; mọi luận điểm/con số gắn `\[n]` cuối câu; cuối câu trả lời có mục

&#x20;  \*\*📚 Chỉ mục nguồn trích dẫn (References)\*\*: `\[1] Tên\_file.pdf | Trang: X | Mục: Tiêu đề — "Trích đoạn nguyên văn..."`.

3\. \*\*Kiểm tra trích dẫn sau khi sinh:\*\* đoạn trích phải khớp (fuzzy ≥ 90) với chunk gốc; `\[n]` phải tồn tại trong danh sách nguồn.

&#x20;  Vi phạm → sinh lại 1 lần, vẫn sai → bỏ trích dẫn lỗi và đánh dấu cảnh báo.

4\. \*\*Response API:\*\* `{answer\_markdown, route, sources\[], tables\[], debug: {rewritten\_query, code, attempts, latency\_ms}}`

&#x20;  (`debug` chỉ trả khi bật cờ admin).



\---



\# 3. DELIVERABLES — LÀM THEO PHASE, DỪNG SAU MỖI PHASE CHỜ TÔI GÕ "TIẾP"

\- \*\*Phase 0:\*\* Danh sách giả định + tối đa 10 câu hỏi làm rõ.

\- \*\*Phase 1:\*\* Cây thư mục (Clean Architecture: `api/`, `application/`, `domain/`, `infrastructure/`), `requirements.txt`

&#x20; (pin version, chạy offline), hướng dẫn cài PostgreSQL/Qdrant native + script tải model về để mang vào mạng nội bộ,

&#x20; DDL PostgreSQL (`departments`, `users`, `files`, `ingestion\_jobs`, `tables\_catalog`, `columns\_catalog`, `column\_values`,

&#x20; `entity\_aliases`, `fewshot\_examples`, `documents`, `chat\_sessions`, `chat\_messages`, `audit\_logs`) + cấu hình collection Qdrant,

&#x20; và các interface (`LLMClient`, `VectorStore`, `Embedder`, `Reranker`, `OCREngine`, `CodeExecutor`).

\- \*\*Phase 2:\*\* `config.py`, `llm\_client.py` (retry exponential backoff, timeout, `chat\_completion`, `structured\_output`

&#x20; với Pydantic validate + fallback parse JSON khi endpoint không hỗ trợ json\_schema).

\- \*\*Phase 3:\*\* `excel\_preprocessor.py` + `catalog\_service.py` + synthetic few-shot + pytest (header nhiều tầng, ô gộp,

&#x20; số/ngày VN, serial date, cột trùng tên, dòng tổng).

\- \*\*Phase 4:\*\* `doc\_ingestor.py` (Docling + OCR + chunking + indexing) + pytest.

\- \*\*Phase 5:\*\* `router.py`, `entity\_linker.py`.

\- \*\*Phase 6:\*\* `tabular\_executor.py` (sandbox DuckDB/Pandas + self-correction) + pytest gồm các case cố tình thoát sandbox.

\- \*\*Phase 7:\*\* `rag\_engine.py`, `hybrid\_engine.py`, `output\_formatter.py`, `prompts.py` (toàn bộ system prompt).

\- \*\*Phase 8:\*\* FastAPI `main.py`: `POST /upload`, `GET /upload/{job\_id}`, `DELETE /files/{file\_id}`, `POST /chat`,

&#x20; `POST /feedback`; auth/RBAC dependency; chạy uvicorn native.



Yêu cầu code: type hints đầy đủ, docstring, logging có cấu trúc, không `pass`/`TODO` ở hàm quan trọng.

Mỗi phase kết thúc bằng checklist "tiêu chí nghiệm thu" và tự đánh giá đạt/chưa đạt.


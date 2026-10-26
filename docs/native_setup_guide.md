# Hướng dẫn Triển khai Native 100% Offline (Air-Gapped LAN)

Tài liệu hướng dẫn cài đặt và vận hành toàn bộ thành phần hệ thống **không sử dụng Docker**, cài native trên Windows Server 2022 và Ubuntu 22.04.

---

## 1. Cài đặt PostgreSQL 16 Native

### Trên Windows Server 2022
1. Tải bộ cài đặt offline `postgresql-16.x-windows-x64.exe` từ trang chủ EnterpriseDB / PostgreSQL.
2. Cài đặt vào ổ đĩa hệ thống (ví dụ `C:\Program Files\PostgreSQL\16`).
3. Đặt mật khẩu cho user `postgres` (mặc định: `postgres`).
4. Khởi động dịch vụ PostgreSQL qua `services.msc` (Service Name: `postgresql-x64-16`).
5. Tạo database và kích hoạt extension nếu cần:
   ```cmd
   "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE rag_enterprise;"
   ```

### Trên Ubuntu 22.04
1. Copy các gói `.deb` offline của PostgreSQL 16 vào máy chủ.
2. Cài đặt bằng `dpkg -i *.deb` hoặc apt offline repository.
3. Kích hoạt và kiểm tra trạng thái:
   ```bash
   sudo systemctl enable postgresql
   sudo systemctl start postgresql
   sudo -u postgres psql -c "CREATE DATABASE rag_enterprise;"
   ```

---

## 2. Cài đặt & Chạy Qdrant Native Binary

### Trên Windows Server
1. Chạy file script PowerShell chuẩn bị sẵn:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\setup_qdrant_service.ps1 -InstallDir "C:\Qdrant"
   ```
2. Nếu máy đã air-gapped, copy file `qdrant.exe` vào `C:\Qdrant`.
3. Khởi động Qdrant:
   - Cách 1: Chạy trực tiếp `C:\Qdrant\run_qdrant.bat`.
   - Cách 2: Đăng ký thành Windows Service tự khởi động cùng máy qua NSSM:
     ```cmd
     nssm install QdrantService "C:\Qdrant\qdrant.exe" "--config-path C:\Qdrant\config.yaml"
     nssm start QdrantService
     ```
4. Kiểm tra sức khỏe Qdrant: `curl http://localhost:6333/healthz` (trả về status `200 OK`).

### Trên Ubuntu 22.04
1. Tải binary `qdrant-x86_64-unknown-linux-gnu.tar.gz`, giải nén và cấp quyền:
   ```bash
   sudo mv qdrant /usr/local/bin/qdrant
   sudo chmod +x /usr/local/bin/qdrant
   ```
2. Tạo file systemd service `/etc/systemd/system/qdrant.service`:
   ```ini
   [Unit]
   Description=Qdrant Vector Database
   After=network.target

   [Service]
   Type=simple
   ExecStart=/usr/local/bin/qdrant
   WorkingDirectory=/var/lib/qdrant
   Restart=always
   User=postgres

   [Install]
   WantedBy=multi-user.target
   ```
3. Khởi động service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now qdrant
   ```

---

## 3. Chuẩn bị Thư viện Python & Model Weights Offline

### Bước 1: Máy có Internet
1. Tải toàn bộ packages theo `requirements.txt`:
   ```bash
   pip download -r requirements.txt -d ./offline_wheels
   ```
2. Chạy script tải trọng số model:
   ```bash
   python ./scripts/download_models.py
   ```
3. Nén thư mục `./offline_wheels` và `./models` vào USB/ổ cứng mang sang máy chủ nội bộ.

### Bước 2: Máy chủ Nội bộ (Air-Gapped)
1. Cài đặt Python 3.11 64-bit.
2. Tạo virtualenv và cài đặt offline:
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   pip install --no-index --find-links=./offline_wheels -r requirements.txt
   ```
3. Copy thư mục `./models` vào thư mục gốc của dự án.
4. Cấu hình file `.env` theo mẫu từ `.env.example`.

"""
Domain-level Custom Exceptions for Enterprise RAG & Tabular Engine.
"""


class EnterpriseRAGException(Exception):
    """Base exception for the application."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class UnsupportedFileError(EnterpriseRAGException):
    """Raised when an uploaded file format is not supported (HTTP 415)."""
    def __init__(self, message: str = "Định dạng file không được hỗ trợ."):
        super().__init__(message, status_code=415)


class FileSizeExceededError(EnterpriseRAGException):
    """Raised when uploaded file exceeds size limit (30MB)."""
    def __init__(self, message: str = "Dung lượng file vượt quá giới hạn tối đa 30MB."):
        super().__init__(message, status_code=413)


class RBACPermissionError(EnterpriseRAGException):
    """Raised when user attempts to access resources outside their permissions."""
    def __init__(self, message: str = "Bạn không có quyền truy cập vào tài nguyên này."):
        super().__init__(message, status_code=403)


class IngestionError(EnterpriseRAGException):
    """Raised when an error occurs during tabular or document ingestion."""
    pass


class SandboxSecurityViolation(EnterpriseRAGException):
    """Raised when malicious or forbidden AST syntax is detected in pandas code."""
    def __init__(self, message: str = "Phát hiện mã nguồn vi phạm chính sách an toàn."):
        super().__init__(message, status_code=400)


class SandboxExecutionTimeout(EnterpriseRAGException):
    """Raised when pandas code execution exceeds the hard timeout limit."""
    def __init__(self, message: str = "Thực thi mã vượt quá thời gian cho phép (15 giây)."):
        super().__init__(message, status_code=408)

class OperatorError(Exception):
    """只包含可以安全展示的错误信息，不包含请求 URL 或凭据。"""

    def __init__(self, message: str, code: str = "upstream", exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


class AuthError(OperatorError):
    def __init__(self, message="认证失败，请执行 xiaoheihe login 重新登录。"):
        super().__init__(message, "auth", 3)


class ProtocolError(OperatorError):
    def __init__(self, message="小黑盒接口响应与当前客户端不兼容。"):
        super().__init__(message, "protocol", 5)

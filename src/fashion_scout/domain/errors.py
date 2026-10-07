class ScoutError(Exception):
    """Safe code/message for future API mapping; never include secrets."""

    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

class SarError(Exception):
    """An actionable Polish message with a stable diagnostic code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

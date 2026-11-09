"""Stable, safe failure details for persistent processing diagnostics."""
class SpecificationProcessingError(ValueError):
    def __init__(self,code,*,details=None):
        self.code=code
        self.details=details or {}
        super().__init__(code+(': '+str(self.details) if self.details else ''))

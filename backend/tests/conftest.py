from __future__ import annotations

import os


os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "integration-internal-token-for-python-tests")
os.environ.setdefault("AIO_ALLOWED_WORKSPACE_ROOTS", os.path.abspath(os.sep))

"""Container healthcheck: exit 0 when the API answers /health. Used by compose.yaml."""
import sys
import urllib.request

try:
    with urllib.request.urlopen("http://localhost:8000/health", timeout=3) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception as e:
    print(e)
    sys.exit(1)

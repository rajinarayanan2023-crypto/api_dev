from slowapi import Limiter
from slowapi.util import get_remote_address

# Keyed by client IP. Behind a reverse proxy, make sure it forwards
# X-Forwarded-For and that the proxy itself is trusted, or this can be spoofed.
limiter = Limiter(key_func=get_remote_address)

#!/usr/bin/env python3
"""
RFSN Security Module v8.2
JWT/API Key authentication, rate limiting, and security middleware.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Dict, Any, Callable
from collections import defaultdict
import threading

from fastapi import Request, HTTPException, Depends, Security
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# =============================================================================
# API KEY AUTHENTICATION
# =============================================================================

class APIKeyManager:
    """Manages API keys for authentication"""
    
    def __init__(self, keys_file: str = "api_keys.json"):
        self.keys_file = keys_file
        self.keys: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load_keys()
    
    def _load_keys(self):
        """Load API keys from file"""
        if os.path.exists(self.keys_file):
            try:
                with open(self.keys_file, 'r') as f:
                    self.keys = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load API keys: {e}")
    
    def _save_keys(self):
        """Save API keys to file"""
        with open(self.keys_file, 'w') as f:
            json.dump(self.keys, f, indent=2)
    
    def generate_key(self, name: str, scopes: list = None) -> str:
        """Generate a new API key"""
        with self._lock:
            key = f"rfsn_{secrets.token_urlsafe(32)}"
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            
            self.keys[key_hash] = {
                "name": name,
                "scopes": scopes or ["read", "write"],
                "created": datetime.utcnow().isoformat(),
                "last_used": None,
                "active": True
            }
            
            self._save_keys()
            
            # Return unhashed key (only shown once)
            return key
    
    def validate_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Validate an API key and return its metadata"""
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        
        with self._lock:
            if key_hash in self.keys and self.keys[key_hash]["active"]:
                self.keys[key_hash]["last_used"] = datetime.utcnow().isoformat()
                self._save_keys()
                return self.keys[key_hash]
        
        return None
    
    def revoke_key(self, key_hash: str) -> bool:
        """Revoke an API key"""
        with self._lock:
            if key_hash in self.keys:
                self.keys[key_hash]["active"] = False
                self._save_keys()
                return True
        return False
    
    def list_keys(self) -> Dict[str, Dict[str, Any]]:
        """List all API keys (without the actual keys)"""
        return {h: {k: v for k, v in info.items()} for h, info in self.keys.items()}


# =============================================================================
# JWT AUTHENTICATION
# =============================================================================

class JWTManager:
    """Simple JWT implementation (no external dependencies)"""
    
    def __init__(self, secret: str = None, expires_hours: int = 24):
        self.secret = secret or os.environ.get("JWT_SECRET", secrets.token_urlsafe(32))
        self.expires_hours = expires_hours
    
    def _base64url_encode(self, data: bytes) -> str:
        import base64
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')
    
    def _base64url_decode(self, data: str) -> bytes:
        import base64
        padding = 4 - len(data) % 4
        if padding != 4:
            data += '=' * padding
        return base64.urlsafe_b64decode(data)
    
    def create_token(self, payload: Dict[str, Any]) -> str:
        """Create a JWT token"""
        header = {"alg": "HS256", "typ": "JWT"}
        
        # Add standard claims
        now = datetime.utcnow()
        payload.update({
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=self.expires_hours)).timestamp()),
        })
        
        # Encode header and payload
        header_b64 = self._base64url_encode(json.dumps(header).encode())
        payload_b64 = self._base64url_encode(json.dumps(payload).encode())
        
        # Create signature
        message = f"{header_b64}.{payload_b64}".encode()
        signature = hmac.new(self.secret.encode(), message, hashlib.sha256).digest()
        signature_b64 = self._base64url_encode(signature)
        
        return f"{header_b64}.{payload_b64}.{signature_b64}"
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a JWT token"""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            
            header_b64, payload_b64, signature_b64 = parts
            
            # Verify signature
            message = f"{header_b64}.{payload_b64}".encode()
            expected_sig = hmac.new(self.secret.encode(), message, hashlib.sha256).digest()
            actual_sig = self._base64url_decode(signature_b64)
            
            if not hmac.compare_digest(expected_sig, actual_sig):
                return None
            
            # Decode payload
            payload = json.loads(self._base64url_decode(payload_b64))
            
            # Check expiration
            if payload.get("exp", 0) < time.time():
                return None
            
            return payload
            
        except Exception as e:
            logger.debug(f"JWT verification failed: {e}")
            return None


# =============================================================================
# RATE LIMITING
# =============================================================================

class RateLimiter:
    """
    Token bucket rate limiter with per-IP tracking.
    """
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        burst_size: int = 10,
        cleanup_interval: int = 300
    ):
        self.rate = requests_per_minute / 60.0  # requests per second
        self.burst_size = burst_size
        self.buckets: Dict[str, Dict[str, float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()
        self.cleanup_interval = cleanup_interval
    
    def _cleanup(self):
        """Remove stale entries"""
        now = time.time()
        if now - self._last_cleanup < self.cleanup_interval:
            return
        
        with self._lock:
            stale_keys = [
                key for key, bucket in self.buckets.items()
                if now - bucket["last_update"] > self.cleanup_interval
            ]
            for key in stale_keys:
                del self.buckets[key]
            self._last_cleanup = now
    
    def is_allowed(self, key: str) -> tuple:
        """
        Check if request is allowed.
        
        Returns:
            (allowed: bool, retry_after: float)
        """
        self._cleanup()
        now = time.time()
        
        with self._lock:
            if key not in self.buckets:
                self.buckets[key] = {
                    "tokens": self.burst_size,
                    "last_update": now
                }
            
            bucket = self.buckets[key]
            
            # Add tokens based on time elapsed
            elapsed = now - bucket["last_update"]
            bucket["tokens"] = min(
                self.burst_size,
                bucket["tokens"] + elapsed * self.rate
            )
            bucket["last_update"] = now
            
            # Check if we have a token
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True, 0
            else:
                # Calculate retry-after
                retry_after = (1 - bucket["tokens"]) / self.rate
                return False, retry_after
    
    def get_stats(self, key: str) -> Dict[str, Any]:
        """Get rate limit stats for a key"""
        with self._lock:
            if key in self.buckets:
                return {
                    "tokens_remaining": self.buckets[key]["tokens"],
                    "limit": self.burst_size,
                    "reset_rate": f"{self.rate:.2f}/sec"
                }
            return {
                "tokens_remaining": self.burst_size,
                "limit": self.burst_size,
                "reset_rate": f"{self.rate:.2f}/sec"
            }


# =============================================================================
# FASTAPI MIDDLEWARE & DEPENDENCIES
# =============================================================================

# Global instances
api_key_manager = APIKeyManager()
jwt_manager = JWTManager()
rate_limiter = RateLimiter(requests_per_minute=120, burst_size=20)

# Security headers
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)


async def get_api_key(api_key: str = Security(api_key_header)) -> Optional[Dict[str, Any]]:
    """Dependency for API key authentication"""
    if not api_key:
        return None
    return api_key_manager.validate_key(api_key)


async def get_jwt_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer_auth)
) -> Optional[Dict[str, Any]]:
    """Dependency for JWT authentication"""
    if not credentials:
        return None
    return jwt_manager.verify_token(credentials.credentials)


async def require_auth(
    api_key: Optional[Dict] = Depends(get_api_key),
    jwt_payload: Optional[Dict] = Depends(get_jwt_token)
):
    """
    Dependency that requires either API key or JWT authentication.
    """
    if api_key:
        return {"type": "api_key", **api_key}
    if jwt_payload:
        return {"type": "jwt", **jwt_payload}
    
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide X-API-Key header or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"}
    )


async def optional_auth(
    api_key: Optional[Dict] = Depends(get_api_key),
    jwt_payload: Optional[Dict] = Depends(get_jwt_token)
) -> Optional[Dict]:
    """
    Dependency for optional authentication.
    Returns auth info if present, None otherwise.
    """
    if api_key:
        return {"type": "api_key", **api_key}
    if jwt_payload:
        return {"type": "jwt", **jwt_payload}
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for rate limiting"""
    
    async def dispatch(self, request: Request, call_next):
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        
        # Check rate limit
        allowed, retry_after = rate_limiter.is_allowed(client_ip)
        
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "retry_after": retry_after,
                    "message": f"Rate limit exceeded. Try again in {retry_after:.1f} seconds."
                },
                headers={"Retry-After": str(int(retry_after) + 1)}
            )
        
        # Add rate limit headers to response
        response = await call_next(request)
        stats = rate_limiter.get_stats(client_ip)
        response.headers["X-RateLimit-Remaining"] = str(int(stats["tokens_remaining"]))
        response.headers["X-RateLimit-Limit"] = str(stats["limit"])
        
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response


def setup_security(app, enable_rate_limit: bool = True, enable_auth: bool = False):
    """
    Setup security middleware for FastAPI app.
    
    Args:
        app: FastAPI application
        enable_rate_limit: Enable rate limiting
        enable_auth: Enable authentication requirement
    """
    app.add_middleware(SecurityHeadersMiddleware)
    
    if enable_rate_limit:
        app.add_middleware(RateLimitMiddleware)
        logger.info("Rate limiting enabled: 120 req/min, burst=20")
    
    if enable_auth:
        logger.info("Authentication enabled")


if __name__ == "__main__":
    # Quick test
    print("Testing Security Module...")
    
    # Test API Key
    key = api_key_manager.generate_key("test")
    print(f"Generated API key: {key[:20]}...")
    
    info = api_key_manager.validate_key(key)
    print(f"Validated: {info['name']}")
    
    # Test JWT
    token = jwt_manager.create_token({"user": "test_user", "role": "admin"})
    print(f"JWT token: {token[:50]}...")
    
    payload = jwt_manager.verify_token(token)
    print(f"JWT payload: {payload}")
    
    # Test Rate Limiter
    for i in range(25):
        allowed, retry = rate_limiter.is_allowed("127.0.0.1")
        if not allowed:
            print(f"Rate limited after {i} requests. Retry in {retry:.1f}s")
            break
    
    print("Tests complete!")

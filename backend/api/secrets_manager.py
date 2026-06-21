"""
Secrets Manager for NiftyMind Trading Application.

Provides secure credential retrieval with multiple backend support:
- AWS Secrets Manager (primary)
- HashiCorp Vault (alternative)
- Local environment variables (fallback for development)

Features:
- In-memory caching with TTL to reduce API calls
- Automatic secret rotation detection
- Secure credential retrieval for all sensitive configuration
- Comprehensive audit logging
"""

import os
import logging
import hashlib
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger("niftymind.secrets")

# Cache TTL in seconds (5 minutes default)
DEFAULT_CACHE_TTL = 300
# Maximum PIN attempts before lockout
MAX_PIN_ATTEMPTS = 5
# PIN lockout duration in seconds (15 minutes)
PIN_LOCKOUT_DURATION = 900


@dataclass
class SecretValue:
    """Wrapper for secret values with metadata."""
    value: str
    version_id: Optional[str] = None
    last_rotated: Optional[float] = None
    cache_timestamp: float = field(default_factory=time.time)

    def is_expired(self, ttl_seconds: int = DEFAULT_CACHE_TTL) -> bool:
        return (time.time() - self.cache_timestamp) > ttl_seconds


class PINAttemptTracker:
    """Track PIN verification attempts to prevent brute-force attacks."""

    def __init__(self):
        self._attempts: Dict[str, Dict[str, Any]] = {}

    def _key(self, identifier: str) -> str:
        return hashlib.sha256(identifier.encode()).hexdigest()[:16]

    def record_attempt(self, identifier: str, success: bool) -> bool:
        """Record a PIN attempt. Returns True if attempt is allowed."""
        key = self._key(identifier)
        now = time.time()

        if key not in self._attempts:
            self._attempts[key] = {"count": 0, "locked_until": 0, "last_attempt": 0}

        entry = self._attempts[key]

        # Check if still locked out
        if now < entry["locked_until"]:
            logger.warning(f"PIN attempt blocked for identifier hash {key}: locked out until {entry['locked_until']}")
            return False

        # Reset counter if lockout period has passed
        if now > entry["locked_until"] and entry["locked_until"] > 0:
            entry["count"] = 0
            entry["locked_until"] = 0

        if success:
            entry["count"] = 0
            entry["locked_until"] = 0
            entry["last_attempt"] = now
            return True

        entry["count"] += 1
        entry["last_attempt"] = now

        if entry["count"] >= MAX_PIN_ATTEMPTS:
            entry["locked_until"] = now + PIN_LOCKOUT_DURATION
            logger.warning(
                f"PIN brute-force protection triggered for identifier hash {key}. "
                f"Locked for {PIN_LOCKOUT_DURATION}s"
            )
            return False

        return True

    def get_remaining_attempts(self, identifier: str) -> int:
        key = self._key(identifier)
        if key not in self._attempts:
            return MAX_PIN_ATTEMPTS
        entry = self._attempts[key]
        if time.time() < entry["locked_until"]:
            return 0
        return max(0, MAX_PIN_ATTEMPTS - entry["count"])

    def is_locked(self, identifier: str) -> bool:
        key = self._key(identifier)
        if key not in self._attempts:
            return False
        return time.time() < self._attempts[key]["locked_until"]


class SecretsManager:
    """
    Unified secrets manager supporting multiple backends.

    Priority order:
    1. AWS Secrets Manager (if AWS_SECRET_MANAGER_ENABLED=true)
    2. HashiCorp Vault (if VAULT_ADDR is set)
    3. Environment variables (fallback)
    """

    def __init__(
        self,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        aws_region: Optional[str] = None,
        aws_secret_name: Optional[str] = None,
        vault_addr: Optional[str] = None,
        vault_token: Optional[str] = None,
        vault_path: Optional[str] = None,
    ):
        self._cache: Dict[str, SecretValue] = {}
        self._cache_ttl = cache_ttl
        self._pin_tracker = PINAttemptTracker()

        # AWS configuration
        self._aws_enabled = os.getenv("AWS_SECRET_MANAGER_ENABLED", "").lower() in ("1", "true", "yes")
        self._aws_region = aws_region or os.getenv("AWS_REGION", "ap-south-1")
        self._aws_secret_name = aws_secret_name or os.getenv("AWS_SECRET_NAME", "niftymind/production")
        self._aws_client = None

        # Vault configuration
        self._vault_addr = vault_addr or os.getenv("VAULT_ADDR", "")
        self._vault_token = vault_token or os.getenv("VAULT_TOKEN", "")
        self._vault_path = vault_path or os.getenv("VAULT_PATH", "secret/data/niftymind")
        self._vault_client = None

        # Initialize backend clients if configured
        self._init_aws_client()
        self._init_vault_client()

    def _init_aws_client(self):
        """Initialize AWS Secrets Manager client if enabled."""
        if not self._aws_enabled:
            return
        try:
            import boto3
            self._aws_client = boto3.client(
                "secretsmanager",
                region_name=self._aws_region,
            )
            logger.info("AWS Secrets Manager client initialized")
        except ImportError:
            logger.warning("boto3 not installed, AWS Secrets Manager unavailable")
            self._aws_enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize AWS Secrets Manager: {e}")
            self._aws_enabled = False

    def _init_vault_client(self):
        """Initialize HashiCorp Vault client if configured."""
        if not self._vault_addr:
            return
        try:
            import hvac
            self._vault_client = hvac.Client(
                url=self._vault_addr,
                token=self._vault_token,
            )
            if not self._vault_client.is_authenticated():
                logger.warning("HashiCorp Vault authentication failed")
                self._vault_client = None
            else:
                logger.info("HashiCorp Vault client initialized")
        except ImportError:
            logger.warning("hvac not installed, HashiCorp Vault unavailable")
            self._vault_client = None
        except Exception as e:
            logger.error(f"Failed to initialize HashiCorp Vault: {e}")
            self._vault_client = None

    def _get_from_aws(self, key: str) -> Optional[str]:
        """Retrieve secret from AWS Secrets Manager."""
        if not self._aws_client:
            return None
        try:
            import botocore.exceptions
            response = self._aws_client.get_secret_value(SecretId=self._aws_secret_name)
            secret_string = response.get("SecretString", "{}")
            import json
            secrets = json.loads(secret_string)
            return secrets.get(key)
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error(f"AWS Secrets Manager error ({error_code}): {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve secret '{key}' from AWS: {e}")
            return None

    def _get_from_vault(self, key: str) -> Optional[str]:
        """Retrieve secret from HashiCorp Vault."""
        if not self._vault_client:
            return None
        try:
            response = self._vault_client.secrets.kv.v2.read_secret_version(
                path=self._vault_path,
            )
            data = response.get("data", {}).get("data", {})
            return data.get(key)
        except Exception as e:
            logger.error(f"Failed to retrieve secret '{key}' from Vault: {e}")
            return None

    def get_secret(self, key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
        """
        Retrieve a secret value with caching.

        Args:
            key: The secret key/name
            default: Default value if secret not found
            required: If True, raises ValueError when secret not found

        Returns:
            The secret value or default
        """
        # Check cache first
        if key in self._cache:
            cached = self._cache[key]
            if not cached.is_expired(self._cache_ttl):
                logger.debug(f"Secret '{key}' served from cache")
                return cached.value
            # Expired - remove from cache
            del self._cache[key]

        value = None
        source = "unknown"

        # Try AWS Secrets Manager first
        if self._aws_enabled and self._aws_client:
            value = self._get_from_aws(key)
            if value is not None:
                source = "aws_secrets_manager"

        # Try HashiCorp Vault second
        if value is None and self._vault_client:
            value = self._get_from_vault(key)
            if value is not None:
                source = "hashicorp_vault"

        # Fallback to environment variable
        if value is None:
            value = os.getenv(key)
            if value is not None:
                source = "environment"

        # Use default if still not found
        if value is None:
            value = default
            if value is not None:
                source = "default"

        # Validate required secrets
        if required and value is None:
            raise ValueError(
                f"Required secret '{key}' not found in any backend "
                f"(AWS: {self._aws_enabled}, Vault: {self._vault_client is not None}, Env: {key in os.environ})"
            )

        # Cache the value if found from a secure backend
        if value is not None and source in ("aws_secrets_manager", "hashicorp_vault"):
            self._cache[key] = SecretValue(
                value=value,
                cache_timestamp=time.time(),
            )

        if value is not None:
            logger.debug(f"Secret '{key}' retrieved from {source}")
        elif required:
            logger.error(f"Required secret '{key}' not found")
        else:
            logger.debug(f"Secret '{key}' not found, using default")

        return value

    def get_required_secret(self, key: str) -> str:
        """Get a required secret. Raises ValueError if not found."""
        return self.get_secret(key, required=True)  # type: ignore[return-value]

    def clear_cache(self):
        """Clear the secret cache. Useful for testing or rotation events."""
        self._cache.clear()
        logger.info("Secret cache cleared")

    def refresh_secret(self, key: str) -> Optional[str]:
        """Force refresh a specific secret from backend."""
        if key in self._cache:
            del self._cache[key]
        return self.get_secret(key)

    def get_pin_tracker(self) -> PINAttemptTracker:
        """Get the PIN attempt tracker for brute-force protection."""
        return self._pin_tracker

    @property
    def is_aws_configured(self) -> bool:
        return self._aws_enabled and self._aws_client is not None

    @property
    def is_vault_configured(self) -> bool:
        return self._vault_client is not None


# Global singleton instance
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get or create the global secrets manager singleton."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def reset_secrets_manager():
    """Reset the global secrets manager singleton."""
    global _secrets_manager
    _secrets_manager = None


def get_secret(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Convenience function to get a secret from the global manager."""
    return get_secrets_manager().get_secret(key, default=default, required=required)


def get_required_secret(key: str) -> str:
    """Convenience function to get a required secret."""
    return get_secrets_manager().get_required_secret(key)

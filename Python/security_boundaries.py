"""
Security Boundaries: Capabilities table and allowlists
Defines what tools/actions are available and constrains their inputs.
"""
import json
import time
import re
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Set, Tuple
from pathlib import Path
from enum import Enum
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    """Raised when a capability is not permitted"""
    pass


class InputValidationError(Exception):
    """Raised when input validation fails"""
    pass


class CapabilityType(Enum):
    """Types of capabilities"""
    TOOL = "tool"
    COMMAND = "command"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    NETWORK_REQUEST = "network_request"
    SYSTEM_OPERATION = "system_operation"


@dataclass
class Capability:
    """A capability with constraints"""
    name: str
    capability_type: CapabilityType
    description: str
    enabled: bool = True
    allowed_inputs: Optional[Dict[str, Any]] = None
    required_permissions: List[str] = field(default_factory=list)
    max_execution_time: float = 30.0
    rate_limit: Optional[int] = None  # Max calls per minute
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "capability_type": self.capability_type.value,
            "description": self.description,
            "enabled": self.enabled,
            "allowed_inputs": self.allowed_inputs,
            "required_permissions": self.required_permissions,
            "max_execution_time": self.max_execution_time,
            "rate_limit": self.rate_limit
        }


class PathAllowlist:
    """
    Manages allowed paths for file operations.
    Prevents unauthorized file access.
    """
    
    def __init__(self):
        """Initialize path allowlist"""
        self._allowed_read_paths: Set[str] = set()
        self._allowed_write_paths: Set[str] = set()
        self._denied_paths: Set[str] = set()
    
    def add_read_path(self, path: str):
        """Add a path to read allowlist"""
        self._allowed_read_paths.add(path)
    
    def add_write_path(self, path: str):
        """Add a path to write allowlist"""
        self._allowed_write_paths.add(path)
    
    def add_denied_path(self, path: str):
        """Add a path to denylist"""
        self._denied_paths.add(path)
    
    def can_read(self, path: str) -> bool:
        """
        Check if path can be read
        
        Args:
            path: Path to check
            
        Returns:
            True if allowed
        """
        # Check denylist first
        for denied in self._denied_paths:
            if self._path_matches(path, denied):
                return False
        
        # Check allowlist
        for allowed in self._allowed_read_paths:
            if self._path_matches(path, allowed):
                return True
        
        return False
    
    def can_write(self, path: str) -> bool:
        """
        Check if path can be written
        
        Args:
            path: Path to check
            
        Returns:
            True if allowed
        """
        # Check denylist first
        for denied in self._denied_paths:
            if self._path_matches(path, denied):
                return False
        
        # Check allowlist
        for allowed in self._allowed_write_paths:
            if self._path_matches(path, allowed):
                return True
        
        return False
    
    def _path_matches(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern (supports wildcards)"""
        # Normalize paths
        path = path.replace("\\", "/")
        pattern = pattern.replace("\\", "/")
        
        # Simple wildcard matching
        regex_pattern = pattern.replace("*", ".*").replace("?", ".")
        regex_pattern = f"^{regex_pattern}$"
        
        try:
            return bool(re.match(regex_pattern, path))
        except re.error:
            return path == pattern


class CommandAllowlist:
    """
    Manages allowed commands and their arguments.
    Prevents arbitrary command execution.
    """
    
    def __init__(self):
        """Initialize command allowlist"""
        self._allowed_commands: Dict[str, Dict[str, Any]] = {}
    
    def add_command(self, command: str, allowed_args: Optional[List[str]] = None,
                   blocked_args: Optional[List[str]] = None):
        """
        Add a command to allowlist
        
        Args:
            command: Command name
            allowed_args: List of allowed argument names
            blocked_args: List of blocked argument names
        """
        self._allowed_commands[command] = {
            "allowed_args": allowed_args or [],
            "blocked_args": blocked_args or []
        }
    
    def can_execute(self, command: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Check if command can be executed with given arguments
        
        Args:
            command: Command name
            args: Command arguments
            
        Returns:
            (allowed, reason)
        """
        if command not in self._allowed_commands:
            return False, f"Command '{command}' not in allowlist"
        
        config = self._allowed_commands[command]
        
        # Check blocked arguments
        for blocked in config["blocked_args"]:
            if blocked in args:
                return False, f"Argument '{blocked}' is blocked"
        
        # Check allowed arguments (if specified)
        if config["allowed_args"]:
            for arg_name in args.keys():
                if arg_name not in config["allowed_args"]:
                    return False, f"Argument '{arg_name}' not allowed"
        
        return True, "Allowed"


class NetworkAllowlist:
    """
    Manages allowed network destinations.
    Prevents unauthorized network access.
    """
    
    def __init__(self):
        """Initialize network allowlist"""
        self._allowed_domains: Set[str] = set()
        self._denied_domains: Set[str] = set()
        self._allowed_protocols: Set[str] = {"https"}  # Default to HTTPS only
    
    def add_domain(self, domain: str):
        """Add domain to allowlist"""
        self._allowed_domains.add(domain.lower())
    
    def add_denied_domain(self, domain: str):
        """Add domain to denylist"""
        self._denied_domains.add(domain.lower())
    
    def add_protocol(self, protocol: str):
        """Add protocol to allowlist"""
        self._allowed_protocols.add(protocol.lower())
    
    def can_access(self, url: str) -> Tuple[bool, str]:
        """
        Check if URL can be accessed
        
        Args:
            url: URL to check
            
        Returns:
            (allowed, reason)
        """
        try:
            parsed = urlparse(url)
            
            # Check protocol
            if parsed.scheme.lower() not in self._allowed_protocols:
                return False, f"Protocol '{parsed.scheme}' not allowed"
            
            # Check denylist
            domain = parsed.netloc.lower()
            for denied in self._denied_domains:
                if domain == denied or domain.endswith(f".{denied}"):
                    return False, f"Domain '{domain}' is blocked"
            
            # Check allowlist (if not empty)
            if self._allowed_domains:
                allowed = False
                for allowed_domain in self._allowed_domains:
                    if domain == allowed_domain or domain.endswith(f".{allowed_domain}"):
                        allowed = True
                        break
                
                if not allowed:
                    return False, f"Domain '{domain}' not in allowlist"
            
            return True, "Allowed"
        
        except Exception as e:
            return False, f"URL parsing error: {e}"


class SecurityBoundary:
    """
    Main security boundary manager.
    Enforces all security constraints.
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize security boundary
        
        Args:
            config_path: Path to security config file
        """
        self._capabilities: Dict[str, Capability] = {}
        self._path_allowlist = PathAllowlist()
        self._command_allowlist = CommandAllowlist()
        self._network_allowlist = NetworkAllowlist()
        
        self._rate_limits: Dict[str, List[float]] = {}
        
        # Load config if provided
        if config_path and config_path.exists():
            self._load_config(config_path)
        
        # Setup default constraints
        self._setup_defaults()
        
        logger.info("SecurityBoundary initialized")
    
    def _setup_defaults(self):
        """Setup default security constraints"""
        # Default safe paths
        self._path_allowlist.add_read_path("memory/*")
        self._path_allowlist.add_read_path("data/*")
        self._path_allowlist.add_write_path("memory/*")
        self._path_allowlist.add_write_path("data/*")
        
        # Deny sensitive paths
        self._path_allowlist.add_denied_path("/etc/*")
        self._path_allowlist.add_denied_path("/root/*")
        self._path_allowlist.add_denied_path("~/.ssh/*")
        self._path_allowlist.add_denied_path("~/.aws/*")
        
        # Default network
        self._network_allowlist.add_protocol("https")
    
    def register_capability(self, capability: Capability):
        """Register a capability"""
        self._capabilities[capability.name] = capability
        logger.debug(f"Registered capability: {capability.name}")
    
    def check_capability(self, capability_name: str,
                        inputs: Optional[Dict[str, Any]] = None,
                        permissions: Optional[List[str]] = None) -> Tuple[bool, str]:
        """
        Check if a capability can be used
        
        Args:
            capability_name: Name of capability
            inputs: Input arguments
            permissions: User permissions
            
        Returns:
            (allowed, reason)
        """
        capability = self._capabilities.get(capability_name)
        if not capability:
            return False, f"Capability '{capability_name}' not found"
        
        if not capability.enabled:
            return False, f"Capability '{capability_name}' is disabled"
        
        # Check required permissions
        if capability.required_permissions:
            user_perms = set(permissions or [])
            required = set(capability.required_permissions)
            if not required.issubset(user_perms):
                missing = required - user_perms
                return False, f"Missing permissions: {missing}"
        
        # Check input constraints
        if capability.allowed_inputs and inputs:
            for key, constraint in capability.allowed_inputs.items():
                if key in inputs:
                    value = inputs[key]
                    
                    # Type check
                    if "type" in constraint:
                        expected_type = constraint["type"]
                        if expected_type == "string" and not isinstance(value, str):
                            return False, f"Input '{key}' must be a string"
                        elif expected_type == "int" and not isinstance(value, int):
                            return False, f"Input '{key}' must be an integer"
                        elif expected_type == "float" and not isinstance(value, (int, float)):
                            return False, f"Input '{key}' must be a number"
                    
                    # Range check
                    if "min" in constraint and isinstance(value, (int, float)):
                        if value < constraint["min"]:
                            return False, f"Input '{key}' below minimum {constraint['min']}"
                    
                    if "max" in constraint and isinstance(value, (int, float)):
                        if value > constraint["max"]:
                            return False, f"Input '{key}' above maximum {constraint['max']}"
                    
                    # Enum check
                    if "enum" in constraint:
                        if value not in constraint["enum"]:
                            return False, f"Input '{key}' must be one of {constraint['enum']}"
        
        # Check rate limit
        if capability.rate_limit:
            if not self._check_rate_limit(capability_name, capability.rate_limit):
                return False, f"Rate limit exceeded for '{capability_name}'"
        
        return True, "Allowed"
    
    def _check_rate_limit(self, capability_name: str, limit: int) -> bool:
        """Check if rate limit is respected"""
        now = time.time()
        window_start = now - 60.0  # 1 minute window
        
        if capability_name not in self._rate_limits:
            self._rate_limits[capability_name] = []
        
        # Filter old timestamps
        self._rate_limits[capability_name] = [
            ts for ts in self._rate_limits[capability_name]
            if ts > window_start
        ]
        
        # Check limit
        return len(self._rate_limits[capability_name]) < limit
    
    def record_capability_use(self, capability_name: str):
        """Record that a capability was used (for rate limiting)"""
        if capability_name not in self._rate_limits:
            self._rate_limits[capability_name] = []

        self._rate_limits[capability_name].append(time.time())
    
    def check_file_access(self, path: str, operation: str) -> Tuple[bool, str]:
        """
        Check if file operation is allowed
        
        Args:
            path: File path
            operation: 'read' or 'write'
            
        Returns:
            (allowed, reason)
        """
        if operation == "read":
            if self._path_allowlist.can_read(path):
                return True, "Allowed"
            return False, f"Read access denied for '{path}'"
        
        elif operation == "write":
            if self._path_allowlist.can_write(path):
                return True, "Allowed"
            return False, f"Write access denied for '{path}'"
        
        return False, f"Invalid operation '{operation}'"
    
    def check_command(self, command: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Check if command execution is allowed
        
        Args:
            command: Command name
            args: Command arguments
            
        Returns:
            (allowed, reason)
        """
        return self._command_allowlist.can_execute(command, args)
    
    def check_network_access(self, url: str) -> Tuple[bool, str]:
        """
        Check if network access is allowed
        
        Args:
            url: URL to access
            
        Returns:
            (allowed, reason)
        """
        return self._network_allowlist.can_access(url)
    
    def validate_tool_call(self, tool_name: str,
                          arguments: Dict[str, Any],
                          permissions: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Validate a tool call against security constraints
        
        Args:
            tool_name: Name of tool
            arguments: Tool arguments
            permissions: User permissions
            
        Returns:
            Validation result with 'allowed' boolean and 'reason' string
        """
        # Check capability
        allowed, reason = self.check_capability(tool_name, arguments, permissions)
        if not allowed:
            return {"allowed": False, "reason": reason}
        
        # Check for file operations
        if "file_path" in arguments:
            path = arguments["file_path"]
            operation = arguments.get("operation", "read")
            allowed, reason = self.check_file_access(path, operation)
            if not allowed:
                return {"allowed": False, "reason": reason}
        
        # Check for network operations
        if "url" in arguments:
            url = arguments["url"]
            allowed, reason = self.check_network_access(url)
            if not allowed:
                return {"allowed": False, "reason": reason}
        
        # Record use
        self.record_capability_use(tool_name)
        
        return {"allowed": True, "reason": "Validated"}
    
    def get_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """Get all capabilities"""
        return {
            name: cap.to_dict()
            for name, cap in self._capabilities.items()
        }
    
    def _load_config(self, config_path: Path):
        """Load security configuration from file"""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Load capabilities
            for cap_config in config.get("capabilities", []):
                capability = Capability(
                    name=cap_config["name"],
                    capability_type=CapabilityType(cap_config["type"]),
                    description=cap_config["description"],
                    enabled=cap_config.get("enabled", True),
                    allowed_inputs=cap_config.get("allowed_inputs"),
                    required_permissions=cap_config.get("required_permissions", []),
                    max_execution_time=cap_config.get("max_execution_time", 30.0),
                    rate_limit=cap_config.get("rate_limit")
                )
                self.register_capability(capability)
            
            # Load path allowlist
            for path in config.get("allowed_read_paths", []):
                self._path_allowlist.add_read_path(path)
            for path in config.get("allowed_write_paths", []):
                self._path_allowlist.add_write_path(path)
            for path in config.get("denied_paths", []):
                self._path_allowlist.add_denied_path(path)
            
            # Load command allowlist
            for cmd_config in config.get("allowed_commands", []):
                self._command_allowlist.add_command(
                    cmd_config["command"],
                    cmd_config.get("allowed_args"),
                    cmd_config.get("blocked_args")
                )
            
            # Load network allowlist
            for domain in config.get("allowed_domains", []):
                self._network_allowlist.add_domain(domain)
            for domain in config.get("denied_domains", []):
                self._network_allowlist.add_denied_domain(domain)
            for protocol in config.get("allowed_protocols", []):
                self._network_allowlist.add_protocol(protocol)
            
            logger.info(f"Loaded security config from {config_path}")
        
        except Exception as e:
            logger.error(f"Failed to load security config: {e}")


# Global security boundary instance
_security_boundary: Optional[SecurityBoundary] = None


def get_security_boundary() -> SecurityBoundary:
    """Get global security boundary instance"""
    global _security_boundary
    if _security_boundary is None:
        _security_boundary = SecurityBoundary()
    return _security_boundary


def init_security_boundary(config_path: Optional[Path] = None) -> SecurityBoundary:
    """
    Initialize global security boundary
    
    Args:
        config_path: Path to security config file
        
    Returns:
        SecurityBoundary instance
    """
    global _security_boundary
    _security_boundary = SecurityBoundary(config_path)
    return _security_boundary


def create_default_config(output_path: Path):
    """Create a default security configuration file"""
    config = {
        "capabilities": [
            {
                "name": "read_memory",
                "type": "file_read",
                "description": "Read from memory files",
                "enabled": True,
                "allowed_inputs": {
                    "file_path": {"type": "string"},
                    "max_size": {"type": "int", "max": 10485760}
                },
                "required_permissions": [],
                "rate_limit": 100
            },
            {
                "name": "write_memory",
                "type": "file_write",
                "description": "Write to memory files",
                "enabled": True,
                "allowed_inputs": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required_permissions": ["memory_write"],
                "rate_limit": 50
            },
            {
                "name": "llm_generate",
                "type": "tool",
                "description": "Generate text with LLM",
                "enabled": True,
                "allowed_inputs": {
                    "prompt": {"type": "string", "max_length": 4096},
                    "max_tokens": {"type": "int", "min": 1, "max": 2048}
                },
                "rate_limit": 60
            }
        ],
        "allowed_read_paths": [
            "memory/*",
            "data/*",
            "config.json"
        ],
        "allowed_write_paths": [
            "memory/*",
            "data/*"
        ],
        "denied_paths": [
            "/etc/*",
            "/root/*",
            "~/.ssh/*",
            "~/.aws/*"
        ],
        "allowed_domains": [
            "api.openai.com",
            "huggingface.co"
        ],
        "denied_domains": [],
        "allowed_protocols": ["https"]
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    logger.info(f"Created default security config: {output_path}")

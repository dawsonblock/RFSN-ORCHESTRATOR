import pytest
import sys
import os
from pathlib import Path

# Add python dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.sanitize import safe_filename_token

def test_safe_filename_token_blocks_traversal():
    """Test that path traversal attempts are neutralized"""
    assert safe_filename_token("../evil") == "evil"
    assert safe_filename_token("..\\evil") == "evil"
    assert safe_filename_token("a/b/c") == "a_b_c"
    assert safe_filename_token("../../etc/passwd") == "etc_passwd"

def test_safe_filename_token_clamps():
    """Test that filenames are clamped to max length"""
    s = safe_filename_token("x" * 500)
    assert len(s) == 64
    assert s == "x" * 64

def test_safe_filename_basic():
    """Test basic filename cleaning"""
    # Implementation preserves spaces (allowed chars: A-Za-z0-9_ -)
    assert safe_filename_token("  My NPC Name  ") == "My NPC Name"
    assert safe_filename_token("Lydia!") == "Lydia"
    assert safe_filename_token("Jarl Balgruuf") == "Jarl Balgruuf"

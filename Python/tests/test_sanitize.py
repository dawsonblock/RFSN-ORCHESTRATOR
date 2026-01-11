from utils.sanitize import safe_filename_token

def test_blocks_traversal():
    assert safe_filename_token("../evil") == "evil"
    assert safe_filename_token("..\\evil") == "evil"
    assert safe_filename_token("a/b/c") == "a_b_c"

def test_clamps_len():
    assert len(safe_filename_token("x"*500)) == 64

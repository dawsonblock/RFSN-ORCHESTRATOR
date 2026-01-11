
import pytest
import time
from streaming_engine import StreamTokenizer

def test_quote_boundary():
    tokenizer = StreamTokenizer()
    # "No." -> punctuation inside quote, followed by space. Should split.
    out = list(tokenizer.process('He said, "No." She left.'))
    # Expected: ['He said, "No."'] then ' She left.' -> next token might trigger 'She left.'
    # Actually process returns list of COMPLETED sentences.
    # 'He said, "No." ' (space triggers split)
    
    # Check if "No." is kept together with "He said,"
    # The tokenizer buffers. 'He said, "No." ' should emit 'He said, "No."'
    
    assert any('No."' in s for s in out)
    assert len(out) >= 1
    assert out[0] == 'He said, "No."'

def test_newline_boundary():
    tokenizer = StreamTokenizer()
    # \n should act as boundary
    out = tokenizer.process("Hello.\nWorld.")
    # Should emit 'Hello.'
    assert "Hello." in out
    assert len(out) >= 1

def test_abbreviation_handling():
    tokenizer = StreamTokenizer()
    out = tokenizer.process("Dr. Smith is here.")
    # Should NOT split at Dr.
    # 'Dr. Smith is here.' 
    # If we pass just this, it might buffer 'Dr. Smith is here.' waiting for next sentence.
    # So let's add a stopper.
    out.extend(tokenizer.process(" Yes."))
    
    # We expect 'Dr. Smith is here.' to be one sentence, not ['Dr.', 'Smith...']
    # And definitely not split at Dr.
    
    # out should contain the full sentence
    full_text = " ".join(out)
    assert "Dr." in full_text
    # Should only split at the end
    assert "Dr." not in out # i.e. it shouldn't be a standalone sentence "Dr."
    assert "Dr. Smith is here." in out

def test_deferred_boundary_flush():
    tokenizer = StreamTokenizer()
    # Punctuation at end of buffer
    out = tokenizer.process("Wait.")
    assert len(out) == 0 # Should defer
    
    # Simulate time passing > 180ms
    # We can't easily monkeypatch time inside the class instance without mocking time module used by module.
    # But we can check that a flush forces it.
    
    out = tokenizer.flush()
    assert len(out) == 1
    assert out[0] == "Wait."

def test_cancellation_of_boundary():
    tokenizer = StreamTokenizer()
    # "Wait." followed immediately by "No..." -> "Wait.No..." (no space)
    # The deferred boundary should be cancelled if next token is alphanumeric
    out = tokenizer.process("Wait.") # Defer
    out2 = tokenizer.process("No") # Should attach
    
    # Should NOT have emitted "Wait."
    assert len(out) == 0
    assert len(out2) == 0 
    
    out3 = tokenizer.process(" ") # Process space
    assert len(out3) == 0 # Still incomplete "Wait.No "
    
    # Finish it
    out4 = tokenizer.process(".")
    if not out4: # Maybe deferred
        out4 = tokenizer.flush()
        
    assert len(out4) >= 1
    assert "Wait.No" in out4[0] # Just check for content
    # We successfully merged them, proving cancellation worked.

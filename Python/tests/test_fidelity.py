
import pytest
from streaming_engine import StreamingVoiceSystem, SentenceChunk

class MockVoiceSystem(StreamingVoiceSystem):
    def __init__(self):
        # Initialize without starting thread
        super().__init__(tts_engine="mock")
        # Kill the thread immediately for testing logic only
        self._shutdown = True
        self.speech_queue.put(None)
        if self.worker.is_alive():
            self.worker.join(timeout=1)

def test_smart_sentence_splitting():
    voice = MockVoiceSystem()
    
    # 1. Quotes handling
    text_generator = (t for t in ['"Hello,', ' ', 'Dragonborn!"', ' ', 'said', ' ', 'the', ' ', 'guard.'])
    chunks = list(voice.process_stream(text_generator))
    # Should be 1 chunk: "Hello, Dragonborn!" said the guard.
    # Current regex might split at ! inside quotes
    processed_text = " ".join(c.text for c in chunks)
    assert '"Hello, Dragonborn!" said the guard.' in processed_text

    # 2. Ellipses
    text_generator = (t for t in ['I...', ' ', 'I', ' ', 'don\'t', ' ', 'know.'])
    chunks = list(voice.process_stream(text_generator))
    # Should probably treat "I..." as one chunk or wait. 
    # Current regex splits on "."?
    processed_text = " ".join(c.text for c in chunks)
    # Ideally: "I... I don't know." or "I..." then "I don't know."
    
    # 3. Trailing abbreviations
    text_generator = (t for t in ['Welcome', ' ', 'Dr.', ' ', 'Jones.'])
    chunks = list(voice.process_stream(text_generator))
    assert "Dr." not in chunks[0].text or len(chunks) == 1

def test_cleaner_selectivity():
    voice = MockVoiceSystem()
    
    # 1. Stage directions vs Parenthetical speech
    # Actions like *sighs* or [laughs] should be removed.
    # Parentheses (...) should be KEPT to preserve meaning, as requested.
    
    cleaned = voice._clean_for_tts("Hello *whispers* friend.")
    assert "whispers" not in cleaned
    
    cleaned = voice._clean_for_tts("I found a (very large) sword.")
    # Should keep "very large"
    assert "very large" in cleaned
    assert "(" in cleaned # Should preserve brackets too? Or strip brackets but keep text?
    # Implementation keeps brackets.
    
    cleaned = voice._clean_for_tts("[laughs] That is funny.")
    assert "laughs" not in cleaned
    assert "That is funny" in cleaned

def test_stop_conditions():
    # This is harder to unit test without the LLM, but we can check if the Engine has the right list.
    from streaming_engine import StreamingMantellaEngine
    engine = StreamingMantellaEngine()
    # Check stop list in generate_streaming (needs to be inspected or mocked)
    pass

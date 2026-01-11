
import sys
import os
import re

# Force current dir
sys.path.append(os.getcwd())

from streaming_engine import StreamTokenizer

import inspect

def test():
    t = StreamTokenizer()
    print(f"Abbreviations sample: {list(t.abbreviations)[:3]}")
    
    # Dump source
    src = inspect.getsource(StreamTokenizer.process)
    print("\n--- SOURCE START ---")
    print(src)
    print("--- SOURCE END ---\n")
    
    t.buffer = "Mr."
    t._pending_boundary = True
    
    print("\nProcessing ' Jones'...")
    sents = t.process(" Jones")
    
    print(f"Sentences: {sents}")
    print(f"Buffer: '{t.buffer}'")
    
    if len(sents) == 0:
        print("PASS: Merged")
    else:
        print("FAIL: Split")

if __name__ == "__main__":
    test()

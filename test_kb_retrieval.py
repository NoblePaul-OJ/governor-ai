#!/usr/bin/env python
"""Quick test to verify KB retrieval is working"""
import sys
sys.path.insert(0, '.')

from app.services.institutional_knowledge import resolve_institutional_query

# Test cases
test_queries = [
    "Who is the dean of FACIT?",
    "Tell me about the dean of computing",
    "Who heads computer science?",
    "Who is the HOD of Cyber Security?",
    "What about the registrar?",
    "Who is the vice chancellor?",
    "Tell me about the board of trustees",
    "Who is the chancellor?",
    "What is the DVC for academic?",
    "Tell me the librarian",
]

print("=" * 60)
print("TESTING KB RETRIEVAL")
print("=" * 60)

for query in test_queries:
    result = resolve_institutional_query(query)
    print(f"\n📌 Query: {query}")
    print(f"   Handled: {result.get('handled', False)}")
    if result.get('handled'):
        print(f"   Confidence: {result.get('confidence', 0)}")
        print(f"   Category: {result.get('category')}")
        print(f"   Freshness: {result.get('freshness')}")
        print(f"   Reply: {result.get('reply', 'N/A')[:100]}...")
    else:
        print("   ❌ NOT HANDLED - Would use fallback")

print("\n" + "=" * 60)

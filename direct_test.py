#!/usr/bin/env python
"""Direct test to check KB loading"""
import json
from pathlib import Path

# Test 1: Load institutional knowledge JSON
kb_path = Path('app/data/institutional_knowledge.json')
try:
    with open(kb_path) as f:
        data = json.load(f)
    print("✅ JSON loaded successfully")
    print(f"   Has deans_of_faculties: {'deans_of_faculties' in data}")
    print(f"   Has heads_of_departments: {'heads_of_departments' in data}")
    print(f"   Has principal_officers: {'principal_officers' in data}")
    print(f"   Has governance: {'governance' in data}")
    print(f"   Has board_of_trustees: {'board_of_trustees' in data}")
    
    # Print dean info
    if 'deans_of_faculties' in data:
        deans = data['deans_of_faculties']
        if 'computing_and_it' in deans:
            facit_dean = deans['computing_and_it']
            print(f"\n✅ FACIT Dean: {facit_dean.get('name')}")
            print(f"   Faculty: {facit_dean.get('faculty')}")
    
    # Print HOD info
    if 'heads_of_departments' in data:
        hods = data['heads_of_departments']
        if 'facit' in hods:
            facit_hods = hods['facit']
            print(f"\n✅ FACIT HODs:")
            for dept, hod in facit_hods.items():
                print(f"   {dept}: {hod}")
                
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Test the resolve function
try:
    from app.services.institutional_knowledge import resolve_institutional_query
    print("\n✅ Module imported successfully")
    
    test_queries = [
        "Who is the dean of FACIT?",
        "Tell me about the dean of computing",
        "Who heads cyber security?",
    ]
    
    for query in test_queries:
        result = resolve_institutional_query(query)
        print(f"\n📌 Query: {query}")
        print(f"   Handled: {result.get('handled', False)}")
        if result.get('handled'):
            print(f"   Reply: {result.get('reply', 'N/A')[:120]}...")
            
except Exception as e:
    print(f"❌ Error in resolve_institutional_query: {e}")
    import traceback
    traceback.print_exc()

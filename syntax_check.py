#!/usr/bin/env python
"""Syntax check for modified files"""
import sys

files_to_check = [
    'app/services/institutional_knowledge.py',
    'app/blueprints/chat/routes.py',
]

print("Checking Python syntax...")
all_ok = True

for filepath in files_to_check:
    try:
        with open(filepath, 'r') as f:
            compile(f.read(), filepath, 'exec')
        print(f"✅ {filepath}")
    except SyntaxError as e:
        print(f"❌ {filepath}: {e}")
        all_ok = False
    except Exception as e:
        print(f"⚠️  {filepath}: {e}")

if all_ok:
    print("\n✅ All files have valid Python syntax!")
else:
    print("\n❌ Some files have syntax errors")
    sys.exit(1)

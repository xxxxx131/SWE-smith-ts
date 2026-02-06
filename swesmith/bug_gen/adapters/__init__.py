from swesmith.bug_gen.adapters.c import get_entities_from_file_c
from swesmith.bug_gen.adapters.cpp import get_entities_from_file_cpp
from swesmith.bug_gen.adapters.c_sharp import get_entities_from_file_c_sharp
from swesmith.bug_gen.adapters.golang import get_entities_from_file_go
from swesmith.bug_gen.adapters.java import get_entities_from_file_java
from swesmith.bug_gen.adapters.javascript import get_entities_from_file_js
from swesmith.bug_gen.adapters.php import get_entities_from_file_php
from swesmith.bug_gen.adapters.python import get_entities_from_file_py
from swesmith.bug_gen.adapters.ruby import get_entities_from_file_rb
from swesmith.bug_gen.adapters.rust import get_entities_from_file_rs
# Phase 1: Added TypeScript support (2026-02-03)
from swesmith.bug_gen.adapters.typescript import get_entities_from_file_ts

get_entities_from_file = {
    ".c": get_entities_from_file_c,
    ".cpp": get_entities_from_file_cpp,
    ".cs": get_entities_from_file_c_sharp,
    ".go": get_entities_from_file_go,
    ".java": get_entities_from_file_java,
    ".js": get_entities_from_file_js,
    # Phase 2: Added JSX support for completeness (2026-02-03)
    ".jsx": get_entities_from_file_js,
    ".php": get_entities_from_file_php,
    ".py": get_entities_from_file_py,
    ".rb": get_entities_from_file_rb,
    ".rs": get_entities_from_file_rs,
    # Phase 1: Added TypeScript/TSX support (2026-02-03)
    ".ts": get_entities_from_file_ts,
    ".tsx": get_entities_from_file_ts,
}

SUPPORTED_EXTS = list(get_entities_from_file.keys())

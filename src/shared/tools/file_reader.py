"""
tools/file_reader.py
Read files from the filesystem — used to read PR diffs saved as temp files.
"""

import json
from crewai.tools import tool


@tool("read_file")
def read_file(file_path: str, start_line: int = 0, max_lines: int = 500) -> str:
    """
    Reads a file from the filesystem. Use this to read PR diff files.

    file_path: absolute path to the file
    start_line: line to start reading from (0-based, default: 0)
    max_lines: maximum lines to read (default: 500). Use multiple calls
               with different start_line to read large files in chunks.

    Returns the file content as text. For large files, read in chunks:
    1. First call: read_file(path, 0, 500) — first 500 lines
    2. Second call: read_file(path, 500, 500) — next 500 lines
    3. Continue until you've read the whole file

    TIP: Check total line count from the first read to know how many
    chunks you need.
    """
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()

        total = len(lines)
        chunk = lines[start_line:start_line + max_lines]
        content = "".join(chunk)

        header = f"[File: {file_path} | Lines {start_line+1}-{min(start_line+max_lines, total)} of {total}]\n"
        return header + content

    except FileNotFoundError:
        return json.dumps({"error": f"File not found: {file_path}"})
    except Exception as e:
        return json.dumps({"error": str(e)})

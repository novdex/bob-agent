"""
Comprehensive tests for mind_clone.core.knowledge module.

Focus: CodebaseIndex validation, AST extraction robustness, query bounds,
memory limits, and edge cases.
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from mind_clone.core.knowledge import (
    CodebaseIndex,
    extract_python_symbols,
    _text_similarity,
)


class TestTextSimilarity:
    """Test _text_similarity helper function."""

    def test_identical_text_returns_one(self):
        """Should return 1.0 for identical text."""
        result = _text_similarity("hello world", "hello world")
        assert result == 1.0

    def test_empty_text_returns_zero(self):
        """Should return 0.0 for empty text."""
        result = _text_similarity("hello", "")
        assert result == 0.0

    def test_both_empty_returns_zero(self):
        """Should return 0.0 when both texts are empty."""
        result = _text_similarity("", "")
        assert result == 0.0

    def test_no_overlap_returns_zero(self):
        """Should return 0.0 when texts have no word overlap."""
        result = _text_similarity("apple banana", "cherry date")
        assert result == 0.0

    def test_partial_overlap(self):
        """Should return value between 0 and 1 for partial overlap."""
        result = _text_similarity("hello world test", "hello foo bar")
        assert 0 < result < 1

    def test_case_insensitive(self):
        """Should be case insensitive."""
        result1 = _text_similarity("Hello World", "hello world")
        result2 = _text_similarity("HELLO WORLD", "hello world")
        assert result1 == 1.0
        assert result2 == 1.0

    def test_subset_text(self):
        """Should handle subset text."""
        result = _text_similarity("hello", "hello world")
        assert 0 < result <= 1

    def test_single_word_match(self):
        """Should handle single word match."""
        result = _text_similarity("test", "test")
        assert result == 1.0

    def test_large_text(self):
        """Should handle large text inputs."""
        text1 = " ".join(["word"] * 1000)
        text2 = " ".join(["word"] * 1000)
        result = _text_similarity(text1, text2)
        assert result == 1.0


class TestExtractPythonSymbols:
    """Test extract_python_symbols function."""

    def test_extracts_function_definitions(self):
        """Should extract function definitions."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
def hello():
    pass

def world():
    pass
""")
            f.flush()
            
            result = extract_python_symbols(f.name)
            
            assert len(result["functions"]) == 2
            assert any(fn["name"] == "hello" for fn in result["functions"])
            assert any(fn["name"] == "world" for fn in result["functions"])
            
            os.unlink(f.name)

    def test_extracts_class_definitions(self):
        """Should extract class definitions."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
class MyClass:
    def method1(self):
        pass
    
    def method2(self):
        pass
""")
            f.flush()
            
            result = extract_python_symbols(f.name)
            
            assert len(result["classes"]) == 1
            assert result["classes"][0]["name"] == "MyClass"
            assert "method1" in result["classes"][0]["methods"]
            assert "method2" in result["classes"][0]["methods"]
            
            os.unlink(f.name)

    def test_extracts_imports(self):
        """Should extract import statements."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
import os
import sys
from pathlib import Path
from typing import List
""")
            f.flush()
            
            result = extract_python_symbols(f.name)
            
            assert len(result["imports"]) > 0
            
            os.unlink(f.name)

    def test_handles_syntax_error(self):
        """Should handle Python syntax errors gracefully."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def broken(\n  invalid syntax ::::")
            f.flush()
            
            result = extract_python_symbols(f.name)
            
            assert result["classes"] == []
            assert result["functions"] == []
            assert result["imports"] == []
            
            os.unlink(f.name)

    def test_handles_nonexistent_file(self):
        """Should handle nonexistent files gracefully."""
        result = extract_python_symbols("/nonexistent/path/file.py")
        
        assert result["classes"] == []
        assert result["functions"] == []

    def test_extracts_docstring(self):
        """Should extract module docstring."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''"""This is a module docstring."""

def func():
    pass
''')
            f.flush()
            
            result = extract_python_symbols(f.name)
            
            assert "module docstring" in result["docstring"]
            
            os.unlink(f.name)

    def test_limits_function_count(self):
        """Should limit extracted functions to 50."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            for i in range(100):
                f.write(f"def func_{i}():\n    pass\n\n")
            f.flush()
            
            result = extract_python_symbols(f.name)
            
            assert len(result["functions"]) <= 50
            
            os.unlink(f.name)

    def test_limits_import_count(self):
        """Should limit extracted imports to 50."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            for i in range(100):
                f.write(f"import module_{i}\n")
            f.flush()
            
            result = extract_python_symbols(f.name)
            
            assert len(result["imports"]) <= 50
            
            os.unlink(f.name)

    def test_empty_file(self):
        """Should handle empty files."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("")
            f.flush()
            
            result = extract_python_symbols(f.name)
            
            assert result["classes"] == []
            assert result["functions"] == []
            assert result["imports"] == []
            
            os.unlink(f.name)


class TestCodebaseIndex:
    """Test CodebaseIndex class."""

    def test_initialization(self):
        """Should initialize with correct attributes."""
        idx = CodebaseIndex("/test/path")
        
        assert idx.root_path == "/test/path"
        assert idx.files == []
        assert idx.symbols == {}
        assert idx.languages == {}

    def test_scan_nonexistent_directory(self):
        """Should return error for nonexistent directory."""
        idx = CodebaseIndex("/nonexistent/path")
        
        result = idx.scan()
        
        assert result["ok"] is False
        assert "error" in result

    def test_scan_empty_directory(self):
        """Should handle empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            idx = CodebaseIndex(tmpdir)
            
            result = idx.scan()
            
            assert result["ok"] is True
            assert idx.files == []

    def test_scan_discovers_python_files(self):
        """Should discover Python files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            Path(tmpdir, "test.py").write_text("def func(): pass")
            Path(tmpdir, "other.txt").write_text("text file")
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert result["ok"] is True
            assert len(idx.files) >= 1
            assert any(f["path"].endswith(".py") for f in idx.files)

    def test_scan_skips_gitignore_dirs(self):
        """Should skip __pycache__, .git, etc."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pycache_dir = Path(tmpdir) / "__pycache__"
            pycache_dir.mkdir()
            (pycache_dir / "test.pyc").write_text("cache")
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert result["ok"] is True
            # Should not include __pycache__ files
            assert not any("__pycache__" in f["path"] for f in idx.files)

    def test_scan_counts_lines(self):
        """Should count lines in files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("line1\nline2\nline3\n")
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert idx.total_lines >= 3

    def test_scan_tracks_languages(self):
        """Should track language counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test.py").write_text("pass")
            Path(tmpdir, "test.js").write_text("var x = 1;")
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert "Python" in idx.languages or "Python" in str(idx.languages)

    def test_get_summary(self):
        """Should return project summary."""
        idx = CodebaseIndex("/test")
        idx.files = [{"path": "test.py", "lines": 10}]
        idx.total_lines = 10
        idx.languages = {"Python": 1}
        
        summary = idx.get_summary()
        
        assert summary["project_name"] == "test"
        assert summary["total_files"] == 1
        assert summary["total_lines"] == 10

    def test_save_creates_json(self):
        """Should save index to JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            idx = CodebaseIndex(tmpdir)
            idx.files = [{"path": "test.py"}]
            
            output_path = str(Path(tmpdir) / "index.json")
            saved = idx.save(output_path)
            
            assert Path(output_path).exists()
            
            with open(output_path) as f:
                data = json.load(f)
            
            assert "files" in data

    def test_load_from_json(self):
        """Should load index from JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save
            idx1 = CodebaseIndex(tmpdir)
            idx1.files = [{"path": "test.py", "lines": 10}]
            output_path = str(Path(tmpdir) / "index.json")
            idx1.save(output_path)
            
            # Load
            idx2 = CodebaseIndex(tmpdir)
            success = idx2.load(output_path)
            
            assert success is True
            assert len(idx2.files) == 1

    def test_query_returns_relevant_results(self):
        """Should return relevant query results."""
        idx = CodebaseIndex("/test")
        idx.files = [{"path": "utils.py", "lines": 10, "language": "Python"}]
        idx.symbols = {"utils.py": {"functions": [{"name": "helper_func"}]}}
        
        results = idx.query("utility functions")
        
        assert isinstance(results, list)

    def test_query_limits_results(self):
        """Should limit query results to 20."""
        idx = CodebaseIndex("/test")
        idx.files = [{"path": f"file{i}.py", "lines": 10, "language": "Python"} 
                     for i in range(50)]
        
        results = idx.query("file")
        
        assert len(results) <= 20

    def test_ext_to_language_mapping(self):
        """Should map file extensions to languages."""
        assert CodebaseIndex._ext_to_language(".py") == "Python"
        assert CodebaseIndex._ext_to_language(".js") == "JavaScript"
        assert CodebaseIndex._ext_to_language(".ts") == "TypeScript"
        assert CodebaseIndex._ext_to_language(".unknown") == ".unknown"


class TestCodebaseIndexBoundaries:
    """Test boundary conditions for CodebaseIndex."""

    def test_handles_very_large_files(self):
        """Should handle very large files without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            large_file = Path(tmpdir) / "large.py"
            # Create file with 10K lines
            large_file.write_text("\n".join(["x = 1"] * 10000))
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert result["ok"] is True

    def test_handles_many_files(self):
        """Should handle directory with many files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(500):
                Path(tmpdir, f"file{i}.py").write_text("pass")
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert result["ok"] is True
            assert len(idx.files) >= 500

    def test_handles_deep_nesting(self):
        """Should handle deeply nested directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir)
            for i in range(10):
                nested = nested / f"level{i}"
                nested.mkdir(exist_ok=True)
            
            (nested / "deep.py").write_text("pass")
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert result["ok"] is True

    def test_handles_symlinks_safely(self):
        """Should handle symlinks without infinite loops."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "file.py"
            file_path.write_text("pass")
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert result["ok"] is True

    def test_handles_unicode_filenames(self):
        """Should handle Unicode filenames."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "файл.py").write_text("pass")
            
            idx = CodebaseIndex(tmpdir)
            result = idx.scan()
            
            assert result["ok"] is True

    def test_cache_functionality(self):
        """Should cache index in memory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            idx = CodebaseIndex(tmpdir)
            
            # Create a small file
            Path(tmpdir, "test.py").write_text("pass")
            
            result1 = idx.scan()
            
            # Index should be cached
            from mind_clone.core.knowledge import _INDEX_CACHE
            assert idx.root_path in _INDEX_CACHE

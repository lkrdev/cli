#!/usr/bin/env python3
"""
Test to ensure that all dependency combinations resolve to the same lock file.

This test verifies that:
1. uv sync --extra all
2. uv sync --extra [all individual extras]

Both resolve to the same lock file, ensuring consistency in dependency resolution.
"""

import subprocess
import tempfile
import shutil
import hashlib
from pathlib import Path
import pytest
import tomllib


def get_file_hash(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    hash_sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


def discover_individual_extras(project_root: Path) -> list[str]:
    """Discover all individual extras from pyproject.toml, excluding 'all'."""
    pyproject_path = project_root / "pyproject.toml"
    
    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")
    
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    
    optional_deps = data.get("project", {}).get("optional-dependencies", {})
    
    # Get all extras except 'all'
    individual_extras = [extra for extra in optional_deps.keys() if extra != "all"]
    
    if not individual_extras:
        raise ValueError("No individual extras found in pyproject.toml")
    
    return individual_extras


def run_uv_sync(project_dir: Path, extras: list[str]) -> Path:
    """Run uv sync with specified extras and return the path to the generated lock file."""
    cmd = ["uv", "sync"]
    for extra in extras:
        cmd.extend(["--extra", extra])
    print(f"Running: {' '.join(cmd)} in {project_dir}")
    
    result = subprocess.run(
        cmd,
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=True
    )
    
    lock_file = project_dir / "uv.lock"
    if not lock_file.exists():
        raise FileNotFoundError(f"Lock file not found at {lock_file}")
    
    return lock_file


def test_dependency_resolution_consistency():
    """Test that all dependency combinations resolve to the same lock file."""
    # Get the current project directory
    project_root = Path(__file__).parent.parent
    
    # Discover individual extras
    individual_extras = discover_individual_extras(project_root)
    print(f"Discovered individual extras: {individual_extras}")
    
    # Create temporary directories for testing
    with tempfile.TemporaryDirectory() as temp_dir1, tempfile.TemporaryDirectory() as temp_dir2:
        temp_dir1_path = Path(temp_dir1)
        temp_dir2_path = Path(temp_dir2)
        
        # Copy project files to temporary directories
        for item in ["pyproject.toml", "README.md", "LICENSE"]:
            src = project_root / item
            if src.exists():
                shutil.copy2(src, temp_dir1_path / item)
                shutil.copy2(src, temp_dir2_path / item)
        
        # Copy the lkr directory
        lkr_src = project_root / "lkr"
        if lkr_src.exists():
            shutil.copytree(lkr_src, temp_dir1_path / "lkr")
            shutil.copytree(lkr_src, temp_dir2_path / "lkr")
        
        try:
            # Test 1: uv sync --extra all
            lock_file_1 = run_uv_sync(temp_dir1_path, ["all"])
            hash_1 = get_file_hash(lock_file_1)
            print(f"Lock file 1 hash: {hash_1}")
            
            # Test 2: uv sync --extra [all individual extras]
            lock_file_2 = run_uv_sync(temp_dir2_path, individual_extras)
            hash_2 = get_file_hash(lock_file_2)
            print(f"Lock file 2 hash: {hash_2}")
            
            # Assert that both lock files are identical
            assert hash_1 == hash_2, (
                f"Lock files are different!\n"
                f"Hash 1 (--extra all): {hash_1}\n"
                f"Hash 2 (--extra {', '.join(individual_extras)}): {hash_2}\n"
                f"This indicates that the dependency combinations do not resolve to the same set of packages."
            )
            
            print("✅ All dependency combinations resolve to the same lock file!")
            
        except subprocess.CalledProcessError as e:
            pytest.fail(f"uv sync failed: {e.stderr}")
        except Exception as e:
            pytest.fail(f"Test failed with error: {e}")


def test_individual_extras_consistency():
    """Test that individual extras are properly defined and don't conflict."""
    project_root = Path(__file__).parent.parent
    pyproject_path = project_root / "pyproject.toml"
    
    if not pyproject_path.exists():
        pytest.skip("pyproject.toml not found")
    
    # Read pyproject.toml to verify the extras are properly defined
    with open(pyproject_path, 'r') as f:
        content = f.read()
    
    # Discover individual extras
    individual_extras = discover_individual_extras(project_root)
    required_extras = individual_extras + ["all"]
    
    # Check that all required extras are defined
    for extra in required_extras:
        assert extra in optional_deps, f"Extra '{extra}' not found in pyproject.toml"
    
    # Check that the 'all' extra includes all individual extras
    assert '"mcp[cli]>=1.9.2"' in content, "mcp dependency not found in 'all' extra"
    assert '"fastapi>=0.115.12"' in content, "fastapi dependency not found in 'all' extra"
    assert '"selenium>=4.32.0"' in content, "selenium dependency not found in 'all' extra"
    assert '"duckdb>=1.2.2"' in content, "duckdb dependency not found in 'all' extra"


if __name__ == "__main__":
    # Run the tests directly if script is executed
    test_dependency_resolution_consistency()
    test_individual_extras_consistency()
    print("All tests passed!") 
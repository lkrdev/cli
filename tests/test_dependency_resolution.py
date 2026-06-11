#!/usr/bin/env python3
"""
Test to ensure that all dependency combinations resolve to the same lock file.

This test verifies that:
1. uv sync --extra all
2. uv sync --extra [all individual extras]

Both resolve to the same lock file, ensuring consistency in dependency resolution.

This test also verifies that the UserAttributeUpdater can be imported, instantiated, and model_dump_json() works
with only the base dependencies (no extras installed).
"""

import subprocess
import tempfile
import shutil
import hashlib
from pathlib import Path
import pytest
import tomllib
import os


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
    
    _result = subprocess.run(
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
    
    # Parse pyproject.toml to get the actual dependencies
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    
    optional_deps = data.get("project", {}).get("optional-dependencies", {})
    
    # Discover individual extras
    individual_extras = discover_individual_extras(project_root)
    required_extras = individual_extras + ["all"]
    
    # Check that all required extras are defined
    for extra in required_extras:
        assert extra in optional_deps, f"Extra '{extra}' not found in pyproject.toml"
    
    # Get all dependencies from individual extras (excluding dev dependencies)
    all_individual_deps = set()
    dev_deps = set()
    for extra in individual_extras:
        if extra in optional_deps:
            if extra == "dev":
                # Dev dependencies are typically not included in 'all'
                dev_deps.update(optional_deps[extra])
            else:
                all_individual_deps.update(optional_deps[extra])
    
    # Get dependencies from the 'all' extra
    all_extra_deps = set(optional_deps.get("all", []))
    
    # Check that the 'all' extra includes all non-dev individual extras
    missing_deps = all_individual_deps - all_extra_deps
    assert not missing_deps, (
        f"The 'all' extra is missing dependencies from individual extras: {missing_deps}\n"
        f"Individual extras dependencies (non-dev): {all_individual_deps}\n"
        f"'all' extra dependencies: {all_extra_deps}"
    )
    
    print(f"✅ 'all' extra includes all {len(all_individual_deps)} non-dev dependencies from individual extras")
    if dev_deps:
        print(f"ℹ️  Dev dependencies ({len(dev_deps)} items) are excluded from 'all' extra as expected")


def test_user_attribute_updater_base_deps_only(tmp_path):
    """
    Test that UserAttributeUpdater can be imported, instantiated, and model_dump_json() works
    in a fresh environment with only base dependencies (no extras installed).
    This is done by creating a temp dir, running 'uv sync' (no extras), and running a subprocess.
    """
    FILENAME = "test_user_attribute_updater.py"
    # Copy minimal project files to temp dir
    project_root = Path(__file__).parent.parent
    temp_dir = Path(tmp_path) / "base_deps_env"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    for item in ["pyproject.toml", "README.md", "LICENSE"]:
        src = project_root / item
        if src.exists():
            shutil.copy2(src, temp_dir / item)
    lkr_src = project_root / "lkr"
    if lkr_src.exists():
        shutil.copytree(lkr_src, temp_dir / "lkr")

    # Run 'uv sync' in the temp dir (no extras)
    subprocess.run(["uv", "sync"], cwd=temp_dir, check=True)

    # Write a small test script to the temp dir
    test_script = temp_dir / FILENAME
    test_script.write_text(
        """
from lkr.tools.classes import UserAttributeUpdater
updater = UserAttributeUpdater(user_attribute='test', value='test', update_type='default')
print(updater.model_dump_json())
"""
    )

    # Run the script using the temp dir as the working directory and PYTHONPATH
    env = dict(**os.environ)
    env["PYTHONPATH"] = str(temp_dir)
    result = subprocess.run(
        ["uv", "run", FILENAME],
        cwd=temp_dir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout.strip()
    assert '"user_attribute":"test"' in output
    assert '"value":"test"' not in output
    assert '"update_type":"default"' in output


if __name__ == "__main__":
    # Run the tests directly if script is executed
    test_dependency_resolution_consistency()
    test_individual_extras_consistency()
    test_user_attribute_updater_base_deps_only("./tmp")
    print("All tests passed!") 



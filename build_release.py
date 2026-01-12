#!/usr/bin/env python3
"""
Unified Build/Release Pipeline
One command to install deps, run tests, smoke test, and build release with version stamping.
"""
import subprocess
import sys
import json
import os
import shutil
import hashlib
import argparse
import traceback
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

class BuildError(Exception):
    """Raised when build fails"""
    pass


class ReleaseBuilder:
    """
    Unified build and release pipeline.
    
    Steps:
    1. Install dependencies
    2. Run tests
    3. Run integration smoke test
    4. Build release zip
    5. Version stamp (commit hash + build time)
    """
    
    def __init__(self, project_root: Path):
        """
        Initialize release builder
        
        Args:
            project_root: Root directory of project
        """
        self.project_root = project_root.resolve()
        self.python_dir = self.project_root / "Python"
        self.release_dir = self.project_root / "releases"
        self.release_dir.mkdir(exist_ok=True)
        
        # Get version info
        self.version_info = self._get_version_info()
        
        print(f"ReleaseBuilder initialized for {self.project_root}")
        print(f"Version: {self.version_info['version']}")
        print(f"Commit: {self.version_info['commit_hash']}")
    
    def _get_version_info(self) -> Dict[str, str]:
        """Get version information"""
        version_info = {
            "version": "unknown",
            "commit_hash": "unknown",
            "build_time": datetime.utcnow().isoformat(),
            "branch": "unknown"
        }
        
        # Get version from version.py
        version_file = self.python_dir / "version.py"
        if version_file.exists():
            try:
                with open(version_file, 'r') as f:
                    content = f.read()
                    # Extract version
                    for line in content.split('\n'):
                        if 'ORCHESTRATOR_VERSION' in line and '=' in line:
                            version = line.split('=')[1].strip().strip('"\'')
                            version_info["version"] = version
                            break
            except Exception as e:
                print(f"Warning: Could not read version.py: {e}")
        
        # Get git info
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version_info["commit_hash"] = result.stdout.strip()[:8]
            
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version_info["branch"] = result.stdout.strip()
        except Exception as e:
            print(f"Warning: Could not get git info: {e}")
        
        return version_info
    
    def _run_command(self, cmd: List[str], cwd: Path,
                     description: str, timeout: int = 300) -> bool:
        """
        Run a command and return success status
        
        Args:
            cmd: Command to run
            cwd: Working directory
            description: Description for logging
            timeout: Command timeout in seconds
            
        Returns:
            True if command succeeded
        """
        print(f"\n{'='*60}")
        print(f"STEP: {description}")
        print(f"Command: {' '.join(cmd)}")
        print(f"{'='*60}")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.stdout:
                print(result.stdout)
            
            if result.stderr:
                print("STDERR:", result.stderr)
            
            if result.returncode != 0:
                print(f"❌ {description} FAILED (exit code: {result.returncode})")
                return False
            
            print(f"✅ {description} SUCCESS")
            return True
        
        except subprocess.TimeoutExpired:
            print(f"❌ {description} TIMEOUT")
            return False
        except Exception as e:
            print(f"❌ {description} ERROR: {e}")
            return False
    
    def install_dependencies(self) -> bool:
        """Install Python dependencies"""
        requirements_file = self.python_dir / "requirements.txt"
        
        if not requirements_file.exists():
            print("⚠️  No requirements.txt found, skipping dependency install")
            return True
        
        return self._run_command(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=self.python_dir,
            description="Installing dependencies",
            timeout=300
        )
    
    def run_tests(self) -> bool:
        """Run all tests"""
        return self._run_command(
            [sys.executable, "-m", "pytest", "tests/", "-v"],
            cwd=self.python_dir,
            description="Running tests",
            timeout=600
        )
    
    def run_smoke_test(self) -> bool:
        """Run integration smoke test"""
        smoke_test = self.python_dir / "tests" / "test_integration.py"
        
        if not smoke_test.exists():
            print("⚠️  No integration smoke test found, skipping")
            return True
        
        return self._run_command(
            [sys.executable, "-m", "pytest", str(smoke_test), "-v"],
            cwd=self.python_dir,
            description="Running integration smoke test",
            timeout=300
        )
    
    def create_version_stamp(self) -> Path:
        """Create version stamp file"""
        stamp_file = self.python_dir / "VERSION.json"
        
        with open(stamp_file, 'w') as f:
            json.dump(self.version_info, f, indent=2)
        
        print(f"✅ Version stamp created: {stamp_file}")
        return stamp_file
    
    def build_release(self) -> Path:
        """
        Build release package
        
        Returns:
            Path to release zip file
        """
        # Create version stamp
        self.create_version_stamp()
        
        # Create release filename
        version = self.version_info["version"]
        commit = self.version_info["commit_hash"]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        release_name = f"rfsn-orchestrator_v{version}_{commit}_{timestamp}"
        release_file = self.release_dir / f"{release_name}.zip"
        
        print(f"\n{'='*60}")
        print(f"Building release: {release_name}")
        print(f"{'='*60}")
        
        # Create temporary directory for release
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            release_path = temp_path / release_name
            release_path.mkdir()
            
            # Copy Python directory
            python_dest = release_path / "Python"
            shutil.copytree(self.python_dir, python_dest,
                          ignore=shutil.ignore_patterns(
                              "__pycache__",
                              "*.pyc",
                              ".pytest_cache",
                              "*.egg-info"
                          ))
            
            # Copy config files
            for config_file in ["config.json", "docker-compose.yml", "Dockerfile"]:
                src = self.project_root / config_file
                if src.exists():
                    shutil.copy2(src, release_path / config_file)
            
            # Copy README
            readme = self.project_root / "README.md"
            if readme.exists():
                shutil.copy2(readme, release_path / "README.md")
            
            # Create release manifest
            manifest = {
                "name": "RFSN Orchestrator",
                "version": version,
                "commit_hash": commit,
                "build_time": self.version_info["build_time"],
                "branch": self.version_info["branch"],
                "files": self._get_file_list(release_path)
            }
            
            with open(release_path / "MANIFEST.json", 'w') as f:
                json.dump(manifest, f, indent=2)
            
            # Create zip
            print("Creating release zip...")
            shutil.make_archive(
                str(release_file.with_suffix('')),
                'zip',
                temp_path,
                release_name
            )
        
        # Calculate checksums
        sha256_hash = self._calculate_checksum(release_file)
        md5_hash = self._calculate_checksum(release_file, algorithm='md5')
        
        print(f"\n✅ Release built: {release_file}")
        print(f"   SHA256: {sha256_hash}")
        print(f"   MD5: {md5_hash}")
        print(f"   Size: {release_file.stat().st_size / 1024 / 1024:.2f} MB")
        
        # Write checksums file
        checksums_file = release_file.with_suffix('.checksums.txt')
        with open(checksums_file, 'w') as f:
            f.write(f"SHA256 ({release_file.name}) = {sha256_hash}\n")
            f.write(f"MD5 ({release_file.name}) = {md5_hash}\n")
        
        print(f"✅ Checksums written: {checksums_file}")
        
        return release_file
    
    def _get_file_list(self, directory: Path) -> List[str]:
        """Get list of files in directory"""
        files = []
        for item in directory.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(directory)
                files.append(str(rel_path))
        return sorted(files)
    
    def _calculate_checksum(self, file_path: Path,
                           algorithm: str = 'sha256') -> str:
        """Calculate file checksum"""
        hash_func = hashlib.new(algorithm)
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hash_func.update(chunk)
        
        return hash_func.hexdigest()
    
    def build_all(self, skip_tests: bool = False,
                 skip_smoke: bool = False) -> Path:
        """
        Run complete build pipeline
        
        Args:
            skip_tests: Skip running tests
            skip_smoke: Skip smoke test
            
        Returns:
            Path to release file
            
        Raises:
            BuildError: If any step fails
        """
        steps_completed = []
        steps_failed = []
        
        # Step 1: Install dependencies
        if not self.install_dependencies():
            steps_failed.append("install_dependencies")
            raise BuildError("Dependency installation failed")
        steps_completed.append("install_dependencies")
        
        # Step 2: Run tests
        if not skip_tests:
            if not self.run_tests():
                steps_failed.append("run_tests")
                raise BuildError("Tests failed")
            steps_completed.append("run_tests")
        else:
            print("⚠️  Skipping tests")
        
        # Step 3: Run smoke test
        if not skip_smoke:
            if not self.run_smoke_test():
                steps_failed.append("run_smoke_test")
                raise BuildError("Smoke test failed")
            steps_completed.append("run_smoke_test")
        else:
            print("⚠️  Skipping smoke test")
        
        # Step 4: Build release
        try:
            release_file = self.build_release()
            steps_completed.append("build_release")
        except Exception as e:
            steps_failed.append("build_release")
            raise BuildError(f"Release build failed: {e}")
        
        # Summary
        print(f"\n{'='*60}")
        print("BUILD SUMMARY")
        print(f"{'='*60}")
        print(f"✅ Completed: {', '.join(steps_completed)}")
        if steps_failed:
            print(f"❌ Failed: {', '.join(steps_failed)}")
        print(f"{'='*60}")
        print(f"🎉 Release successfully built!")
        print(f"   File: {release_file}")
        print(f"{'='*60}")
        
        return release_file


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="RFSN Orchestrator Build/Release Pipeline"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Project root directory"
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests"
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip smoke test"
    )
    
    args = parser.parse_args()
    
    try:
        builder = ReleaseBuilder(args.project_root)
        release_file = builder.build_all(
            skip_tests=args.skip_tests,
            skip_smoke=args.skip_smoke
        )
        
        sys.exit(0)
    
    except BuildError as e:
        print(f"\n❌ BUILD FAILED: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Build cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

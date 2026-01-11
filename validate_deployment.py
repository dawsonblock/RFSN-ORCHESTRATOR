#!/usr/bin/env python3
"""
RFSN Orchestrator v8.1 - Deployment Validator
Pre-flight checks before production deployment.
"""

import subprocess
import sys
import json
from pathlib import Path


def run_tests():
    """Run the test suite"""
    print("\n📋 Running Test Suite...")
    print("-" * 40)
    
    python_dir = Path(__file__).parent / "Python"
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=python_dir,
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        # Count passed tests
        lines = result.stdout.split("\n")
        passed = sum(1 for l in lines if "PASSED" in l)
        print(f"✅ All tests passed ({passed} tests)")
        return True, passed
    else:
        # Count failures
        lines = result.stdout.split("\n")
        failed = sum(1 for l in lines if "FAILED" in l)
        print(f"❌ {failed} tests failed")
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
        return False, 0


def check_imports():
    """Verify all modules import cleanly"""
    print("\n📦 Checking Module Imports...")
    print("-" * 40)
    
    python_dir = Path(__file__).parent / "Python"
    sys.path.insert(0, str(python_dir))
    
    modules = [
        ("streaming_engine", "StreamingVoiceSystem"),
        ("piper_tts", "PiperTTSEngine"),
        ("memory_manager", "ConversationManager"),
        ("utils.sanitize", "safe_filename_token"),
        ("security", "setup_security"),
        ("orchestrator", "app"),
        ("structured_logging", "configure_logging"),
    ]
    
    all_ok = True
    for module_name, class_name in modules:
        try:
            if "." in module_name:
                import importlib
                module = importlib.import_module(module_name)
            else:
                module = __import__(module_name)
            
            cls = getattr(module, class_name)
            print(f"✅ {module_name}.{class_name}")
        except Exception as e:
            print(f"❌ {module_name}: {e}")
            all_ok = False
    
    return all_ok


def check_config():
    """Verify configuration file"""
    print("\n⚙️  Checking Configuration...")
    print("-" * 40)
    
    config_path = Path(__file__).parent / "config.json"
    
    if not config_path.exists():
        print("⚠️  config.json not found (will use defaults)")
        return True
    
    try:
        config = json.loads(config_path.read_text())
        required_keys = ["model_path", "piper_enabled", "memory_enabled"]
        
        for key in required_keys:
            if key in config:
                print(f"✅ {key}: {config[key]}")
            else:
                print(f"⚠️  {key}: missing (will use default)")
        
        return True
    except Exception as e:
        print(f"❌ Config error: {e}")
        return False


def check_directories():
    """Verify required directories exist"""
    print("\n📁 Checking Directories...")
    print("-" * 40)
    
    base_dir = Path(__file__).parent
    
    dirs = [
        base_dir / "Python",
        base_dir / "Python" / "tests",
        base_dir / "Models",
        base_dir / "Dashboard",
    ]
    
    all_ok = True
    for d in dirs:
        if d.exists():
            print(f"✅ {d.relative_to(base_dir)}/")
        else:
            print(f"⚠️  {d.relative_to(base_dir)}/ (creating...)")
            d.mkdir(parents=True, exist_ok=True)
    
    return True


def generate_report():
    """Generate deployment report"""
    print("\n" + "=" * 60)
    print("DEPLOYMENT VALIDATION REPORT")
    print("=" * 60 + "\n")
    
    results = {}
    
    # Run all checks
    results["directories"] = check_directories()
    results["config"] = check_config()
    results["imports"] = check_imports()
    test_passed, test_count = run_tests()
    results["tests"] = test_passed
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = all(results.values())
    
    for check, passed in results.items():
        status = "✅" if passed else "❌"
        print(f"  {status} {check.capitalize()}")
    
    print()
    
    if all_passed:
        print("🚀 READY FOR DEPLOYMENT")
        print(f"   {test_count} tests passed")
        return 0
    else:
        print("❌ DEPLOYMENT BLOCKED - Fix issues above")
        return 1


def main():
    print("\n" + "=" * 60)
    print("RFSN ORCHESTRATOR v8.1 - DEPLOYMENT VALIDATOR")
    print("=" * 60)
    
    exit_code = generate_report()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

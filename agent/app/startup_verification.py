#!/usr/bin/env python3
"""
Startup verification script to ensure all critical modules are available
This should be called at the very beginning of the application
"""

import os
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('StartupVerification')

def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def verify_environment():
    """Verify the runtime environment is properly configured"""
    logger.info("="*60)
    logger.info("STARTUP VERIFICATION")
    logger.info("="*60)
    failed_checks = []
    
    # 1. Check Python version
    logger.info(f"Python version: {sys.version}")
    
    # 2. Check working directory
    logger.info(f"Working directory: {os.getcwd()}")
    
    # 3. Check Python path
    logger.info(f"Python path: {sys.path}")
    
    # 4. List Python files in current directory
    current_dir = os.getcwd()
    logger.info(f"\nPython files in {current_dir}:")
    try:
        files = [f for f in os.listdir(current_dir) if f.endswith('.py')]
        for f in sorted(files):
            size = os.path.getsize(f)
            logger.info(f"  - {f} ({size} bytes)")
            
        # Specifically check for callback_system.py
        if 'callback_system.py' in files:
            logger.info("✅ callback_system.py found in current directory")
        else:
            logger.error("❌ callback_system.py NOT FOUND in current directory")
            failed_checks.append("callback_system.py missing")
            
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        failed_checks.append(f"file listing failed: {e}")
    
    # 5. Try to import critical modules
    logger.info("\nTesting module imports:")
    
    modules_to_test = [
        'azure.data.tables',
        'callback_system',
        'user_functions',
        'teams_integration'
    ]
    
    for module_name in modules_to_test:
        try:
            __import__(module_name)
            logger.info(f"✅ {module_name} - OK")
        except ImportError as e:
            logger.error(f"❌ {module_name} - FAILED: {e}")
            failed_checks.append(f"module import failed: {module_name}")
    
    # 6. Check critical environment variables
    logger.info("\nEnvironment variables:")
    critical_vars = [
        'AZURE_STORAGE_CONNECTION_STRING',
        'D365_CLIENT_ID',
        'D365_CLIENT_SECRET',
        'D365_RESOURCE_URL'
    ]
    
    for var in critical_vars:
        value = os.getenv(var)
        if value:
            logger.info(f"✅ {var} - SET (length: {len(value)})")
        else:
            logger.warning(f"⚠️  {var} - NOT SET")

    require_storage = _env_enabled("REQUIRE_AZURE_STORAGE_CONNECTION_STRING", default=True)
    allow_storage_fallback = _env_enabled("ALLOW_STORAGE_FALLBACK", default=False)
    has_storage_connection = bool(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
    if require_storage and not has_storage_connection and not allow_storage_fallback:
        logger.error(
            "❌ Storage config gate failed: AZURE_STORAGE_CONNECTION_STRING is required. "
            "Set ALLOW_STORAGE_FALLBACK=true only for controlled exceptions."
        )
        failed_checks.append("missing required AZURE_STORAGE_CONNECTION_STRING")
    
    # 7. Special callback system verification
    logger.info("\nCallback system verification:")
    try:
        import callback_system
        if hasattr(callback_system, 'callback_system'):
            if callback_system.callback_system:
                logger.info("✅ callback_system instance initialized")
            else:
                logger.warning("⚠️ callback_system instance is None (check Azure Storage)")
                if require_storage and not allow_storage_fallback:
                    failed_checks.append("callback_system not initialized with required storage")
        else:
            logger.error("❌ callback_system module imported but instance not found")
            failed_checks.append("callback_system instance missing")
    except Exception as e:
        logger.error(f"❌ callback_system verification failed: {e}")
        failed_checks.append("callback_system verification failed")

    if failed_checks:
        logger.error("\nSTARTUP GATE FAILED")
        for check in failed_checks:
            logger.error(f" - {check}")
        logger.info("="*60)
        return False
    
    logger.info("="*60)
    logger.info("STARTUP VERIFICATION COMPLETE")
    logger.info("="*60)
    return True

if __name__ == "__main__":
    if not verify_environment():
        sys.exit(1)

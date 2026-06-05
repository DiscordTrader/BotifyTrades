"""Version information for India Trading Bot"""

APP_VERSION = "1.0.0"
BUILD_DATE = "2026-01-17"
BUILD_TYPE = "DEV"

def get_version():
    return APP_VERSION

def get_build_info():
    return {
        "version": APP_VERSION,
        "build_date": BUILD_DATE,
        "build_type": BUILD_TYPE
    }

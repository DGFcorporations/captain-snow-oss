from setuptools import setup, find_packages

setup(
    name="captainsnow",
    version="0.3.0",
    packages=find_packages(),
    install_requires=[
        "click", "pyyaml", "groq", "httpx", "openai",
        "chromadb", "sqlite-utils", "playwright", "python-telegram-bot",
        "stripe", "yfinance", "python-frontmatter", "Pillow", "aiofiles",
        "python-dotenv", "tqdm", "rich", "beautifulsoup4",
        # Phase 2
        "duckduckgo-search", "pyairtable", "supabase",
        "google-auth-oauthlib", "google-api-python-client", "googlemaps",
        # Production runtime
        "fastapi", "uvicorn[standard]",
    ],
    entry_points={
        "console_scripts": [
            "captainsnow = captainsnow.ui.cli:main"
        ]
    }
)

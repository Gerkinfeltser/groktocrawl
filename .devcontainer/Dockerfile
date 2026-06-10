FROM mcr.microsoft.com/devcontainers/python:3.12

# Install additional tools
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        curl \
        htop \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright system dependencies (needed if running browser tests locally)
RUN pip install --no-cache-dir playwright \
    && playwright install chromium --with-deps \
    && pip uninstall -y playwright

# Verify Python setup
RUN python3 --version && pip --version

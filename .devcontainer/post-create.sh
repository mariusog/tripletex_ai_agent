#!/usr/bin/env bash
set -euo pipefail

# Install bun
curl -fsSL https://bun.sh/install | bash
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"

# Install gcloud CLI via official apt repo (Debian bookworm)
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
sudo apt-get update -qq && sudo apt-get install -y -q google-cloud-cli

# Install Python dependencies
pip install --upgrade pip
pip install -e ".[dev]"

echo "DevContainer ready — node $(node --version), bun $(bun --version), python $(python --version)"

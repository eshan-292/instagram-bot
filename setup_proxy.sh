#!/usr/bin/env bash
# setup_proxy.sh — Generate WireGuard configs from Proton VPN and upload as GitHub secrets
#
# Usage:
#   1. Create a FREE Proton VPN account at https://account.protonvpn.com/signup
#   2. Go to https://account.protonvpn.com/downloads → WireGuard configuration
#   3. Generate 6 configs (one per persona, different servers):
#      - Maya:          US server  → save as wg_maya.conf
#      - Aryan:         Netherlands → save as wg_aryan.conf
#      - ChooseWisely:  Japan      → save as wg_choosewisely.conf
#      - ModernTruths:  Romania    → save as wg_moderntruths.conf
#      - Rhea:          Poland     → save as wg_rhea.conf
#      - Sofia:         US (different server) → save as wg_sofia.conf
#   4. Place all .conf files in this directory
#   5. Run: bash setup_proxy.sh
#
# This script uploads each config as a GitHub secret.
# The bot workflows will automatically pick them up on the next run.

set -euo pipefail

REPO="eshan-292/instagram-bot"

declare -A PERSONA_SECRETS=(
  ["maya"]="WG_CONFIG_MAYA"
  ["aryan"]="WG_CONFIG_ARYAN"
  ["choosewisely"]="WG_CONFIG_CHOOSEWISELY"
  ["moderntruths"]="WG_CONFIG_MODERNTRUTHS"
  ["rhea"]="WG_CONFIG_RHEA"
  ["sofia"]="WG_CONFIG_SOFIA"
)

echo "=== Proxy Setup: Proton VPN + wireproxy ==="
echo ""

uploaded=0
missing=0

for persona in maya aryan choosewisely moderntruths rhea sofia; do
  config_file="wg_${persona}.conf"
  secret_name="${PERSONA_SECRETS[$persona]}"

  if [ -f "$config_file" ]; then
    echo "Uploading $config_file → secret $secret_name"
    gh secret set "$secret_name" --repo "$REPO" < "$config_file"
    uploaded=$((uploaded + 1))
  else
    echo "SKIP: $config_file not found"
    missing=$((missing + 1))
  fi
done

echo ""
echo "Done: $uploaded uploaded, $missing missing"

if [ $uploaded -gt 0 ]; then
  echo ""
  echo "Proxy will activate on the next workflow run for uploaded personas."
  echo "Each persona will route through a different VPN exit IP."
fi

if [ $missing -gt 0 ]; then
  echo ""
  echo "To generate missing configs:"
  echo "  1. Go to https://account.protonvpn.com/downloads"
  echo "  2. Select 'WireGuard' → pick a server → 'Create'"
  echo "  3. Download and save as wg_<persona>.conf"
  echo "  4. Re-run this script"
fi

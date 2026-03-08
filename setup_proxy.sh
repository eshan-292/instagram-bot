#!/usr/bin/env bash
# setup_proxy.sh — Upload WireGuard configs as GitHub secrets for VPN proxy
#
# Usage:
#   1. Create a FREE Proton VPN account at https://account.protonvpn.com/signup
#   2. Go to https://account.protonvpn.com/downloads → WireGuard configuration
#   3. Generate 6 configs (one per persona, different servers):
#      - Maya:          Japan (closest to India)  → save as wg_maya.conf
#      - Aryan:         Japan (different server)   → save as wg_aryan.conf
#      - ChooseWisely:  US                         → save as wg_choosewisely.conf
#      - ModernTruths:  Netherlands                → save as wg_moderntruths.conf
#      - Rhea:          Romania                    → save as wg_rhea.conf
#      - Sofia:         Poland                     → save as wg_sofia.conf
#   4. Place all .conf files in this directory
#   5. Run: bash setup_proxy.sh
#
# This script uploads each config as a GitHub secret.
# The bot workflows will automatically pick them up on the next run.

set -eo pipefail

REPO="eshan-292/instagram-bot"

echo "=== Proxy Setup: Proton VPN + wireproxy ==="
echo ""

uploaded=0
missing=0

# Simple loop — no associative arrays (works on macOS bash 3)
for pair in \
  "maya:WG_CONFIG_MAYA" \
  "aryan:WG_CONFIG_ARYAN" \
  "choosewisely:WG_CONFIG_CHOOSEWISELY" \
  "moderntruths:WG_CONFIG_MODERNTRUTHS" \
  "rhea:WG_CONFIG_RHEA" \
  "sofia:WG_CONFIG_SOFIA"; do

  persona="${pair%%:*}"
  secret_name="${pair##*:}"
  config_file="wg_${persona}.conf"

  # Check for wrong format (.ovpn = OpenVPN, we need WireGuard .conf)
  if [ -f "wg_${persona}.ovpn" ] && [ ! -f "$config_file" ]; then
    echo "ERROR: wg_${persona}.ovpn is OpenVPN format — wireproxy needs WireGuard!"
    echo "       Go to account.protonvpn.com/downloads → 'WireGuard configuration'"
    echo "       Generate a .conf file (starts with [Interface]), not .ovpn"
    missing=$((missing + 1))
    continue
  fi

  if [ -f "$config_file" ]; then
    # Verify it's actually WireGuard format
    if grep -q "\[Interface\]" "$config_file" 2>/dev/null; then
      echo "Uploading $config_file → secret $secret_name"
      gh secret set "$secret_name" --repo "$REPO" < "$config_file"
      uploaded=$((uploaded + 1))
    else
      echo "ERROR: $config_file doesn't look like WireGuard format (missing [Interface])"
      echo "       Make sure you downloaded the WireGuard config, not OpenVPN"
      missing=$((missing + 1))
    fi
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

#!/usr/bin/env python3
"""FOL API Key Validator — Quick health check for all configured providers.

Usage:
    python3 setup/validate_keys.py              # validate all configured keys
    python3 setup/validate_keys.py --all        # show all providers (configured + missing)
    python3 setup/validate_keys.py openai       # validate only OpenAI
    python3 setup/validate_keys.py openai anthropic  # validate specific providers
"""

from __future__ import annotations

import os
import sys

# Add project root to path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "fol"))

try:
    from fol.modules.llm.key_manager import KeyManager, PROVIDERS, get_key_manager
except ImportError:
    from modules.llm.key_manager import KeyManager, PROVIDERS, get_key_manager


def main():
    km = KeyManager()

    # Parse args
    show_all = "--all" in sys.argv
    target_providers = [a for a in sys.argv[1:] if not a.startswith("-")]

    print("\n🧠 FOL API Key Validator\n")

    if show_all:
        print("All providers:\n")
        for name, spec in PROVIDERS.items():
            key = km.get_key(name)
            status = "✅ configured" if key else "⬜ not set"
            print(f"  {spec.display_name:<30} {status}")
        print()

    if target_providers:
        # Validate specific providers
        for provider in target_providers:
            if provider not in PROVIDERS:
                print(f"  ❌ Unknown provider: {provider}")
                continue
            result = km.validate(provider)
            print(f"  {result}")
    else:
        # Validate all configured
        configured = km.configured_providers()
        if not configured:
            print("  No API keys configured. Run: python3 setup/setup_wizard.py\n")
            return

        print(f"Validating {len(configured)} configured provider(s)...\n")
        results = km.validate_all()
        for name, result in results.items():
            print(f"  {result}")

    # Summary
    print()
    configured = km.configured_providers()
    missing = km.missing_providers()

    if configured:
        print(f"  ✅ Configured: {', '.join(configured)}")
    if missing:
        print(f"  ⬜ Not set:    {', '.join(missing)}")

    print()


if __name__ == "__main__":
    main()

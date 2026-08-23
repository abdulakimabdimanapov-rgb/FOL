#!/usr/bin/env python3
"""FOL Setup Wizard — Interactive API key registration and validation.

This script walks the user through:
  1. Choosing which AI providers to configure
  2. Entering API keys for each provider
  3. Validating each key with a real test request
  4. Selecting a brain backend (API keys vs Freebuff)
  5. Writing everything to .env

Usage:
    cd fol-app && python3 ../setup/setup_wizard.py

Or from project root:
    python3 setup/setup_wizard.py
"""

from __future__ import annotations

import os
import sys
import time

# Add project root to path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "fol"))

try:
    from fol.modules.llm.key_manager import KeyManager, PROVIDERS, get_key_manager
except ImportError:
    from modules.llm.key_manager import KeyManager, PROVIDERS, get_key_manager


# ---------------------------------------------------------------------------
# Terminal colors
# ---------------------------------------------------------------------------

class C:
    """ANSI color codes for terminal output."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    CYAN    = "\033[36m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"


def banner():
    """Print the setup wizard banner."""
    print(f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🧠  FOL Setup Wizard                                      ║
║                                                              ║
║   Configure API keys for AI providers and choose your brain. ║
║   The wizard validates every key automatically.              ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{C.RESET}
""")


def print_provider_list():
    """Print all available providers with numbers."""
    print(f"{C.BOLD}Available AI providers:{C.RESET}\n")
    for i, (name, spec) in enumerate(PROVIDERS.items(), 1):
        key = os.environ.get(spec.env_var, "").strip()
        status = f"{C.GREEN}✅ configured{C.RESET}" if key else f"{C.DIM}⬜ not set{C.RESET}"
        print(f"  {C.CYAN}{i}.{C.RESET} {spec.display_name:<30} {status}")
        print(f"     {C.DIM}{spec.description}{C.RESET}")
    print()


def ask_providers() -> list[str]:
    """Ask user which providers to configure."""
    print(f"{C.BOLD}Which providers do you want to configure?{C.RESET}")
    print(f"  Enter numbers separated by commas (e.g. {C.CYAN}1,3,4{C.RESET})")
    print(f"  Or type {C.CYAN}all{C.RESET} to configure all providers")
    print(f"  Or type {C.CYAN}skip{C.RESET} to use existing .env settings")
    print()

    choice = input(f"{C.YELLOW}Your choice > {C.RESET}").strip().lower()

    if choice in ("skip", ""):
        return []
    if choice == "all":
        return list(PROVIDERS.keys())

    selected = []
    provider_names = list(PROVIDERS.keys())
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(provider_names):
                selected.append(provider_names[idx])
            else:
                print(f"  {C.RED}Invalid number: {part}{C.RESET}")
        elif part in PROVIDERS:
            selected.append(part)
        else:
            print(f"  {C.RED}Unknown provider: {part}{C.RESET}")

    return list(dict.fromkeys(selected))  # deduplicate, preserve order


def ask_key(spec) -> str | None:
    """Ask user for an API key for a provider."""
    current = os.environ.get(spec.env_var, "").strip()
    if current:
        preview = f"{current[:8]}...{current[-4:]}" if len(current) > 12 else "***"
        print(f"\n  {C.GREEN}Current key:{C.RESET} {preview}")
        print(f"  {C.DIM}Press Enter to keep, or paste a new key{C.RESET}")
    else:
        print(f"\n  {C.DIM}No key currently set{C.RESET}")

    key = input(f"  {C.YELLOW}{spec.env_var} > {C.RESET}").strip()

    if not key and current:
        return current  # keep existing
    if not key:
        return None

    # Basic format check
    if spec.key_prefix and not key.startswith(spec.key_prefix):
        print(f"  {C.YELLOW}⚠ Key doesn't start with '{spec.key_prefix}' — may be wrong format, but will try anyway{C.RESET}")

    return key


def validate_with_spinner(provider: str, key: str, km: KeyManager):
    """Validate a key with a spinning indicator."""
    sys.stdout.write(f"  {C.CYAN}⏳ Validating {provider} key...{C.RESET}")
    sys.stdout.flush()

    result = km.validate(provider, key)
    # Clear the spinner line
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()

    if result.ok:
        print(f"  {C.GREEN}✅ {provider.upper()}:{C.RESET} {result.message} ({result.latency_ms:.0f}ms)")
    elif result.status == "rate_limited":
        print(f"  {C.YELLOW}⏳ {provider.upper()}:{C.RESET} Rate limited — key may be valid but quota exceeded")
    elif result.status == "invalid_key":
        print(f"  {C.RED}🔑 {provider.upper()}:{C.RESET} Invalid key — double-check your API key")
    else:
        print(f"  {C.RED}❌ {provider.upper()}:{C.RESET} {result.message}")

    return result


def choose_brain() -> str:
    """Ask user which brain backend to use."""
    print(f"""
{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║  Choose your AI brain backend                              ║
╚══════════════════════════════════════════════════════════════╝{C.RESET}

  {C.CYAN}1.{C.RESET} {C.GREEN}API Keys{C.RESET} (recommended) — Uses your configured API keys.
     Brain runs through OpenAI / Anthropic / Gemini / OpenRouter.
     Pick the best model from your available providers.
     {C.DIM}FOL_BRAIN=current{C.RESET}

  {C.CYAN}2.{C.RESET} {C.MAGENTA}Freebuff{C.RESET} — Uses Freebuff models (DeepSeek V4, MiMo 2.5)
     through OpenRouter. Free, fast. Requires OPENROUTER_API_KEY.
     {C.DIM}FOL_BRAIN=freebuff{C.RESET}

  {C.CYAN}3.{C.RESET} {C.BLUE}Both{C.RESET} — Freebuff primary, API keys as fallback.
     Best of both worlds. Freebuff first, then your keys.
     {C.DIM}FOL_BRAIN=freebuff (with fallback to current){C.RESET}

  {C.CYAN}4.{C.RESET} {C.DIM}Skip{C.RESET} — Keep current .env setting unchanged.
""")

    choice = input(f"{C.YELLOW}Your choice (1-4) > {C.RESET}").strip()

    mapping = {"1": "current", "2": "freebuff", "3": "freebuff", "4": "skip"}
    return mapping.get(choice, "skip")


def choose_primary_model(km: KeyManager) -> str | None:
    """Ask user which model to use as primary (based on configured providers)."""
    configured = km.configured_providers()
    if not configured:
        return None

    print(f"\n{C.BOLD}Available primary models (based on your keys):{C.RESET}\n")

    models = []
    if "openrouter" in configured:
        models.append(("openrouter/deepseek/deepseek-v4-flash:free", "DeepSeek V4 Flash (free, smart)"))
    if "openai" in configured:
        models.append(("gpt-4o-mini", "GPT-4o Mini (fast, cheap)"))
        models.append(("gpt-4o", "GPT-4o (powerful)"))
    if "anthropic" in configured:
        models.append(("claude-sonnet-4-20250514", "Claude Sonnet (balanced)"))
    if "gemini" in configured:
        models.append(("gemini/gemini-2.0-flash", "Gemini 2.0 Flash (free, fast)"))
    if "groq" in configured:
        models.append(("groq/llama3-70b-8192", "Groq Llama 3 70B (free, fast)"))
    if "deepseek" in configured:
        models.append(("deepseek-chat", "DeepSeek Chat ($0.14/M tokens)"))
    if "xai" in configured:
        models.append(("xai/grok-3", "xAI Grok-3"))

    for i, (model, desc) in enumerate(models, 1):
        print(f"  {C.CYAN}{i}.{C.RESET} {model:<45} {C.DIM}{desc}{C.RESET}")

    print(f"\n  {C.DIM}Or enter a custom model name (e.g. openrouter/meta-llama/llama-3.1-8b-instruct:free){C.RESET}")

    choice = input(f"\n{C.YELLOW}Your choice > {C.RESET}").strip()

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            return models[idx][0]

    return choice if choice else None


def write_env(updates: dict[str, str], env_path: str = ".env"):
    """Write key-value pairs to .env file."""
    km = KeyManager()
    km.save_to_env(updates, env_path)
    print(f"\n  {C.GREEN}✅ Updated {env_path} with {len(updates)} setting(s){C.RESET}")


def print_final_summary(km: KeyManager, brain_choice: str):
    """Print a summary of what was configured."""
    print(f"""
{C.BOLD}{C.GREEN}╔══════════════════════════════════════════════════════════════╗
║  ✅  Setup Complete!                                         ║
╚══════════════════════════════════════════════════════════════╝{C.RESET}
""")

    configured = km.configured_providers()
    print(f"  {C.BOLD}Configured providers:{C.RESET}")
    for name in configured:
        spec = PROVIDERS[name]
        print(f"    {C.GREEN}✅{C.RESET} {spec.display_name}")

    missing = km.missing_providers()
    if missing:
        print(f"\n  {C.DIM}Skipped:{C.RESET}")
        for name in missing:
            print(f"    {C.DIM}⬜ {PROVIDERS[name].display_name}{C.RESET}")

    brain_names = {
        "current": "API Keys (Current LLM)",
        "freebuff": "Freebuff (DeepSeek V4, MiMo 2.5)",
        "skip": "(unchanged)",
    }
    print(f"\n  {C.BOLD}Brain:{C.RESET} {brain_names.get(brain_choice, brain_choice)}")

    print(f"""
{C.CYAN}To start FOL:{C.RESET}
  {C.DIM}./run_all.sh{C.RESET}          # all services
  {C.DIM}cd fol-app && swift run{C.RESET}   # Mac app only
""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Run the interactive setup wizard."""
    banner()

    # Step 1: Choose providers
    print(f"{C.BOLD}Step 1: Choose AI Providers{C.RESET}")
    print_provider_list()
    selected = ask_providers()

    if not selected:
        print(f"\n  {C.DIM}Keeping existing .env settings.{C.RESET}")
    else:
        # Step 2: Enter keys
        print(f"\n{C.BOLD}Step 2: Enter API Keys{C.RESET}")
        km = KeyManager()
        new_keys: dict[str, str] = {}
        results: dict[str, str] = {}

        for provider_name in selected:
            spec = PROVIDERS[provider_name]
            print(f"\n  {C.BOLD}{spec.display_name}{C.RESET}")
            print(f"  {C.DIM}{spec.description}{C.RESET}")

            key = ask_key(spec)
            if not key:
                print(f"  {C.DIM}Skipped{C.RESET}")
                continue

            # Validate
            result = validate_with_spinner(provider_name, key, km)
            new_keys[spec.env_var] = key
            results[provider_name] = result.status

        # Step 3: Write to .env
        if new_keys:
            print(f"\n{C.BOLD}Step 3: Saving to .env{C.RESET}")
            env_path = os.path.join(_project_root, ".env")
            write_env(new_keys, env_path)

    # Step 4: Choose brain
    print(f"\n{C.BOLD}Step 4: Choose Brain Backend{C.RESET}")
    brain_choice = choose_brain()

    if brain_choice != "skip":
        km = KeyManager()

        if brain_choice == "current":
            # Ask for primary model
            primary = choose_primary_model(km)
            updates = {"FOL_BRAIN": "current"}
            if primary:
                updates["LLM_MODEL"] = primary
            env_path = os.path.join(_project_root, ".env")
            write_env(updates, env_path)

        elif brain_choice == "freebuff":
            # Freebuff needs OpenRouter key
            if not km.get_key("openrouter"):
                print(f"\n  {C.YELLOW}⚠ Freebuff needs OPENROUTER_API_KEY.{C.RESET}")
                print(f"  {C.DIM}Get a free key at https://openrouter.ai{C.RESET}")
                key = input(f"  {C.YELLOW}OpenRouter key (or Enter to skip) > {C.RESET}").strip()
                if key:
                    # Validate
                    result = validate_with_spinner("openrouter", key, km)
                    if result.ok or result.status == "rate_limited":
                        env_path = os.path.join(_project_root, ".env")
                        write_env({
                            "OPENROUTER_API_KEY": key,
                            "FOL_BRAIN": "freebuff",
                            "LLM_MODEL": "openrouter/deepseek/deepseek-v4-flash:free",
                        }, env_path)
                    else:
                        print(f"  {C.RED}Key validation failed. Falling back to API Keys brain.{C.RESET}")
                        env_path = os.path.join(_project_root, ".env")
                        write_env({"FOL_BRAIN": "current"}, env_path)
                        brain_choice = "current"
                else:
                    print(f"  {C.DIM}No key provided. Using API Keys brain.{C.RESET}")
                    env_path = os.path.join(_project_root, ".env")
                    write_env({"FOL_BRAIN": "current"}, env_path)
                    brain_choice = "current"
            else:
                env_path = os.path.join(_project_root, ".env")
                write_env({
                    "FOL_BRAIN": "freebuff",
                    "LLM_MODEL": "openrouter/deepseek/deepseek-v4-flash:free",
                }, env_path)

    # Final summary
    km = KeyManager()
    print_final_summary(km, brain_choice)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{C.DIM}Setup cancelled.{C.RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{C.RED}Error: {e}{C.RESET}")
        sys.exit(1)

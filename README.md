# FOL (SecondSelf) — My Personal AI Assistant for macOS

Hey! This is **FOL**, an AI assistant I built to run right on my MacBook. The main idea was to create a helper that sits in the screen notch, understands what I'm doing, and helps automate annoying daily desktop tasks without me having to switch windows or copy-paste things manually.

##  Why I Built It

I wanted an assistant that feels like a native part of macOS rather than just another open tab in a browser. I designed it to remember my context, help me with daily tasks, and execute desktop actions using simple voice commands or text.

##  Main Features

- **Notch UI:** A custom panel built with SwiftUI that sits right in the MacBook screen notch.
- **Voice Control:** Uses local MLX Whisper on Apple Silicon so I can speak to it directly.
- **Desktop Automation:** Can control apps, take screenshots, click buttons, and read browser context via PyAutoGUI and Chrome CDP.
- **Safety Gate:** A 5-level risk system (`ConfirmationGate`) that asks for my manual approval before executing any sensitive action or system command.
- **Memory Consolidation:** Automatically organizes daily notes, facts, and preferences into my Obsidian Vault.
- **Bilingual Support:** Handles mixed English and Russian prompts easily.

##  How It Works

The system is split into three main parts:
1. **Orchestrator (FastAPI, Port 8420):** Handles LLM routing, agent logic, and streaming responses back to the UI.
2. **Agent Server (Python, Port 8421):** Executes desktop and browser commands on macOS.
3. **FOL Core API (Port 8754):** Manages memory (Obsidian), local voice models (STT/TTS), and tool execution rules.

##  Getting Started

1. Clone the repository and set up your `.env` file:
   ```bash
   cp .env.example .env
   pip install -r requirements.txt

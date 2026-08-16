"""Obsidian Memory Integration — Layer 5 Semantic Memory.

Модули:
- config.py: настройки подключения к Obsidian Local REST API
- client.py: HTTP клиент (read_note, write_note, search, check_connection)
- vault.py: управление структурой папок и CRUD заметок
- sync.py: синхронизация ~/.secondself/ ↔ Obsidian vault
- linker.py: Semantic Linker (LLM-генерация связей)
- tools.py: инструменты для FOL LLM агента
"""

__version__ = "0.1.0"

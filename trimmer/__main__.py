"""Запуск пакета как приложения: python -m trimmer."""

import sys

from trimmer.app import run_app

if __name__ == "__main__":
    sys.exit(run_app())

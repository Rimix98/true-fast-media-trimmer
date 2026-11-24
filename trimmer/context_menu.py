"""Интеграция «Медиа Обрезчик» в контекстное меню Windows.

Платформо-зависимый код (winreg, cp866) вынесен в
trimmer.platform_support — этот модуль сохранён как точка входа
для совместимости.
"""

from trimmer.platform_support import register_context_menu

__all__ = ["register_context_menu"]

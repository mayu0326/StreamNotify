import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

from v4.core.templates import template_utils

logger = logging.getLogger("v4.templates")

class TemplateEngine:
    """
    Handles rendering of notification templates using template_utils.
    Acts as a high-level wrapper/facade for the GUI and other components.
    """
    def __init__(self):
        # template_utils manages environment and filters internally per function call
        # or via shared helpers, so we don't strictly need a persistent env here
        # unless we want to cache templates.
        # For simplicity and consistency with template_utils, we'll delegate.
        pass

    def get_template_text(self, template_type: str) -> str:
        """
        Get raw template text from file.
        Uses template_utils to resolve the file path.
        """
        try:
            # Resolve path using template_utils logic (env vars -> default -> inference)
            path = template_utils.get_template_path(template_type)
            if not path:
                logger.warning(f"Template path not found for type: {template_type}")
                return ""

            p = Path(path)
            if not p.exists():
                logger.warning(f"Template file does not exist: {path}")
                return ""

            with open(p, "r", encoding="utf-8") as f:
                return f.read()

        except Exception as e:
            logger.error(f"Failed to get template text ({template_type}): {e}")
            return ""

    def save_template_text(self, template_type: str, content: str) -> bool:
        """
        Save raw template text to file.
        Uses template_utils to handle saving.
        """
        success, msg = template_utils.save_template_file(template_type, content)
        if hasattr(success, 'result'): # Handle tuple return if distinct from bool (it returns (bool, str))
            pass

        if success:
            logger.info(f"✅ Template saved: {template_type}")
        else:
            logger.error(f"Failed to save template ({template_type}): {msg}")
        return success

    def render_preview(self, template_type: str, custom_content: str) -> str:
        """
        Render a preview using custom content and sample data from template_utils.
        """
        success, result = template_utils.preview_template(template_type, custom_content)
        if success:
            return result
        else:
            return f"Preview generation failed: {result}"

    def render(self, template_type: str, context: Dict[str, Any]) -> Optional[str]:
        """
        Render a template with actual context.
        """
        try:
            # 1. Resolve path
            path = template_utils.get_template_path(template_type)

            # 2. Load template object (with fallback logic)
            # We pass 'path' as the first arg. default_path can be None as util handles defaults if path is None/invalid?
            # actually load_template_with_fallback(path, default_path, type)
            # If path is None, it tries default_path.
            template_obj = template_utils.load_template_with_fallback(path, template_type=template_type)

            if not template_obj:
                return None

            # 3. Render
            return template_utils.render_template(template_obj, context, template_type=template_type)

        except Exception as e:
            logger.error(f"❌ Template rendering failed ({template_type}): {e}")
            return None

    def get_available_template_types(self) -> List[str]:
        """Get list of defined template types"""
        return list(template_utils.TEMPLATE_REQUIRED_KEYS.keys())

    def get_template_args(self, template_type: str) -> List[Tuple[str, str]]:
        """Get available arguments for a template type"""
        return template_utils.get_template_args_for_dialog(template_type)

# Singleton
templates = TemplateEngine()

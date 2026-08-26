"""
GANG Template Engine
Jinja2-based template rendering with custom filters
"""

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

class TemplateEngine:
    def __init__(self, templates_dir: Path):
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Add custom filters
        self.env.filters['formatdate'] = self._format_date
        self.env.filters['date'] = self._format_date
        self.env.filters['tojson_script'] = self._tojson_script
        self.env.filters['safe_url'] = self._safe_url

    @staticmethod
    def _safe_url(value):
        """Allow only relative site paths or http(s) URLs."""
        if not isinstance(value, str):
            return ''
        value = value.strip()
        if not value or value == '#':
            return ''
        if value.startswith('/') and not value.startswith('//'):
            return value
        from urllib.parse import urlparse
        parsed = urlparse(value)
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            return value
        return ''

    @staticmethod
    def _tojson_script(data):
        import json
        from markupsafe import Markup
        return Markup(
            json.dumps(data, indent=2, default=str)
            .replace('<', '\\u003c')
            .replace('>', '\\u003e')
            .replace('&', '\\u0026')
        )
    
    def _format_date(self, date_str: str, format: str = '%B %d, %Y') -> str:
        """Format date string"""
        if isinstance(date_str, str):
            try:
                date_obj = datetime.fromisoformat(str(date_str))
                return date_obj.strftime(format)
            except Exception:
                return date_str
        elif hasattr(date_str, 'strftime'):
            return date_str.strftime(format)
        return str(date_str)
    
    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a template with context"""
        template = self.env.get_template(template_name)
        return template.render(**context)
    
    def render_string(self, template_string: str, context: Dict[str, Any]) -> str:
        """Render a template string with context"""
        template = self.env.from_string(template_string)
        return template.render(**context)


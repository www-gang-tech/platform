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
    
    def _parse_date(self, value):
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _format_date(self, date_str: str, format: str = "long") -> str:
        """Format date string. Default is 'February 5, 2026'."""
        date_obj = self._parse_date(date_str)
        if date_obj is None:
            return str(date_str) if date_str else ""
        if format in ("news", "w3c"):
            return f"{date_obj.day} {date_obj.strftime('%B')} {date_obj.year}"
        if format in ("long", "%B %d, %Y", "%B %-d, %Y"):
            return f"{date_obj.strftime('%B')} {date_obj.day}, {date_obj.year}"
        return date_obj.strftime(format)
    
    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a template with context"""
        template = self.env.get_template(template_name)
        return template.render(**context)
    
    def render_string(self, template_string: str, context: Dict[str, Any]) -> str:
        """Render a template string with context"""
        template = self.env.from_string(template_string)
        return template.render(**context)


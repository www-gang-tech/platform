"""
GANG Template Engine
Jinja2-based template rendering with custom filters
"""

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
from urllib.parse import quote

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
        # Path-safe tag encoding (encodes "/" unlike Jinja urlencode)
        self.env.filters['tagencode'] = self._tagencode

    @staticmethod
    def _tagencode(value: Any) -> str:
        """Encode a tag for /tags/<segment>/ paths (matches tag_path_segment)."""
        return quote(str(value).strip(), safe='-_.~')
    
    def _format_date(self, date_str: str, format: str = '%B %d, %Y') -> str:
        """Format date string"""
        if isinstance(date_str, str):
            try:
                date_obj = datetime.fromisoformat(str(date_str))
                return date_obj.strftime(format)
            except:
                return date_str
        elif isinstance(date_str, datetime):
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


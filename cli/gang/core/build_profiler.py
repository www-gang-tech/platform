"""
GANG Build Profiler
Track and analyze build performance.
"""

import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import json


class BuildProfiler:
    """Profile build performance and track metrics"""
    
    def __init__(self):
        self.metrics = {
            'start_time': None,
            'end_time': None,
            'total_duration': 0,
            'stages': {},
            'file_counts': {},
            'sizes': {}
        }
        self.stage_stack = []
        self.runs_file = Path('.lighthouseci') / 'build-performance.json'
        self.runs_file.parent.mkdir(parents=True, exist_ok=True)
    
    def start(self):
        """Start profiling"""
        self.metrics['start_time'] = time.time()
    
    def end(self):
        """End profiling"""
        self.metrics['end_time'] = time.time()
        self.metrics['total_duration'] = self.metrics['end_time'] - self.metrics['start_time']
    
    def stage(self, name: str):
        """Context manager for profiling a build stage"""
        return BuildStage(self, name)
    
    def record_stage(self, name: str, duration: float):
        """Record a completed stage"""
        if name not in self.metrics['stages']:
            self.metrics['stages'][name] = []
        self.metrics['stages'][name].append(duration)
    
    def record_files(self, content_type: str, count: int):
        """Record file counts"""
        self.metrics['file_counts'][content_type] = count
    
    def record_size(self, category: str, bytes_size: int):
        """Record size metrics"""
        self.metrics['sizes'][category] = bytes_size
    
    def get_summary(self) -> Dict[str, Any]:
        """Get build performance summary"""
        if not self.metrics['total_duration']:
            return {}
        
        summary = {
            'total_duration_ms': round(self.metrics['total_duration'] * 1000),
            'stages': {},
            'files': self.metrics['file_counts'],
            'sizes': self.metrics['sizes'],
            'timestamp': datetime.now().isoformat()
        }
        
        # Calculate stage durations
        for stage_name, durations in self.metrics['stages'].items():
            total_ms = round(sum(durations) * 1000)
            summary['stages'][stage_name] = total_ms
        
        return summary
    
    def save_run(self):
        """Save this run's metrics"""
        summary = self.get_summary()
        if not summary:
            return
        
        # Load previous runs
        runs = []
        if self.runs_file.exists():
            try:
                with open(self.runs_file) as f:
                    data = json.load(f)
                    runs = data.get('runs', [])
            except:
                runs = []
        
        # Add this run
        runs.append(summary)
        
        # Keep last 50 runs
        runs = runs[-50:]
        
        # Save
        with open(self.runs_file, 'w') as f:
            json.dump({'runs': runs}, f, indent=2)
    
    def get_comparison(self) -> Optional[Dict[str, Any]]:
        """Compare with previous run"""
        if not self.runs_file.exists():
            return None
        
        try:
            with open(self.runs_file) as f:
                data = json.load(f)
                runs = data.get('runs', [])
                
                if len(runs) < 2:
                    return None
                
                current = runs[-1]
                previous = runs[-2]
                
                comparison = {
                    'current_ms': current['total_duration_ms'],
                    'previous_ms': previous['total_duration_ms'],
                    'diff_ms': current['total_duration_ms'] - previous['total_duration_ms'],
                    'diff_percent': 0
                }
                
                if previous['total_duration_ms'] > 0:
                    comparison['diff_percent'] = (comparison['diff_ms'] / previous['total_duration_ms']) * 100
                
                return comparison
        except:
            return None
    
    def format_report(self) -> str:
        """Format performance report"""
        summary = self.get_summary()
        if not summary:
            return "No performance data collected"
        
        report = []
        report.append("=" * 60)
        report.append("⚡ Build Performance Report")
        report.append("=" * 60)
        report.append("")
        
        # Total duration
        total_ms = summary['total_duration_ms']
        report.append(f"Total build time: {total_ms}ms ({total_ms/1000:.2f}s)")
        report.append("")
        
        # Stage breakdown
        if summary['stages']:
            report.append("📊 Stage Breakdown:")
            stages = sorted(summary['stages'].items(), key=lambda x: x[1], reverse=True)
            for stage, duration_ms in stages:
                percent = (duration_ms / total_ms) * 100 if total_ms > 0 else 0
                report.append(f"├─ {stage}: {duration_ms}ms ({percent:.1f}%)")
            report.append("")
        
        # File counts
        if summary['files']:
            report.append("📝 Files Processed:")
            for content_type, count in summary['files'].items():
                report.append(f"├─ {content_type}: {count}")
            report.append("")
        
        # Sizes
        if summary['sizes']:
            report.append("📦 Output Sizes:")
            for category, size_bytes in summary['sizes'].items():
                size_kb = size_bytes / 1024
                report.append(f"├─ {category}: {size_kb:.1f}KB")
            report.append("")
        
        # Comparison with previous run
        comparison = self.get_comparison()
        if comparison:
            diff_ms = comparison['diff_ms']
            diff_percent = comparison['diff_percent']
            
            if diff_ms < 0:
                symbol = "🚀"
                direction = "faster"
                diff_ms = abs(diff_ms)
            else:
                symbol = "🐌"
                direction = "slower"
            
            report.append(f"{symbol} vs previous: {diff_ms}ms {direction} ({abs(diff_percent):.1f}%)")
            report.append("")
        
        report.append("=" * 60)
        
        return '\n'.join(report)


class BuildStage:
    """Context manager for profiling a build stage"""
    
    def __init__(self, profiler: BuildProfiler, name: str):
        self.profiler = profiler
        self.name = name
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        self.profiler.record_stage(self.name, duration)


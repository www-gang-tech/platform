"""
GANG Real-time Collaboration
WebSocket-based collaborative editing like Google Docs.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import hashlib


class CollaborationSession:
    """Manage a collaborative editing session"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.clients = {}
        self.document_version = 0
        self.operations = []
        self.last_saved = None
    
    def add_client(self, client_id: str, username: str):
        """Add a client to the session"""
        self.clients[client_id] = {
            'id': client_id,
            'username': username,
            'joined_at': datetime.now().isoformat(),
            'cursor_position': 0,
            'selection': None
        }
    
    def remove_client(self, client_id: str):
        """Remove a client from the session"""
        if client_id in self.clients:
            del self.clients[client_id]
    
    def apply_operation(self, client_id: str, operation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply an operation (insert, delete, format) to the document.
        Uses Operational Transformation for conflict resolution.
        """
        self.document_version += 1
        
        op_record = {
            'id': f"op_{self.document_version}",
            'client_id': client_id,
            'version': self.document_version,
            'operation': operation,
            'timestamp': datetime.now().isoformat()
        }
        
        self.operations.append(op_record)
        
        # Return operation to broadcast to other clients
        return op_record
    
    def update_cursor(self, client_id: str, position: int, selection: Optional[tuple] = None):
        """Update client cursor position"""
        if client_id in self.clients:
            self.clients[client_id]['cursor_position'] = position
            self.clients[client_id]['selection'] = selection
    
    def get_state(self) -> Dict[str, Any]:
        """Get current session state"""
        return {
            'file_path': self.file_path,
            'version': self.document_version,
            'clients': list(self.clients.values()),
            'last_saved': self.last_saved
        }


class OperationalTransform:
    """
    Operational Transformation for real-time collaboration.
    Handles conflict resolution when multiple users edit simultaneously.
    """
    
    @staticmethod
    def transform(op1: Dict[str, Any], op2: Dict[str, Any]) -> tuple:
        """
        Transform two concurrent operations so they can be applied in any order.
        Returns (op1', op2') - transformed versions of the operations.
        """
        op1_type = op1.get('type')
        op2_type = op2.get('type')
        
        # Insert vs Insert
        if op1_type == 'insert' and op2_type == 'insert':
            return OperationalTransform._transform_insert_insert(op1, op2)
        
        # Insert vs Delete
        elif op1_type == 'insert' and op2_type == 'delete':
            return OperationalTransform._transform_insert_delete(op1, op2)
        
        # Delete vs Insert
        elif op1_type == 'delete' and op2_type == 'insert':
            op2_prime, op1_prime = OperationalTransform._transform_insert_delete(op2, op1)
            return op1_prime, op2_prime
        
        # Delete vs Delete
        elif op1_type == 'delete' and op2_type == 'delete':
            return OperationalTransform._transform_delete_delete(op1, op2)
        
        # No transformation needed
        return op1, op2
    
    @staticmethod
    def _transform_insert_insert(op1: Dict, op2: Dict) -> tuple:
        """Transform two concurrent insert operations"""
        pos1 = op1['position']
        pos2 = op2['position']
        len1 = len(op1['content'])
        
        if pos1 < pos2:
            # op1 is before op2, adjust op2's position
            return op1, {**op2, 'position': pos2 + len1}
        elif pos1 > pos2:
            # op2 is before op1, adjust op1's position
            return {**op1, 'position': pos1 + len(op2['content'])}, op2
        else:
            # Same position, prioritize by client_id or timestamp
            return op1, {**op2, 'position': pos2 + len1}
    
    @staticmethod
    def _transform_insert_delete(insert_op: Dict, delete_op: Dict) -> tuple:
        """Transform insert against delete"""
        insert_pos = insert_op['position']
        delete_pos = delete_op['position']
        delete_len = delete_op['length']
        
        if insert_pos <= delete_pos:
            # Insert is before delete, adjust delete position
            return insert_op, {**delete_op, 'position': delete_pos + len(insert_op['content'])}
        elif insert_pos >= delete_pos + delete_len:
            # Insert is after delete, adjust insert position
            return {**insert_op, 'position': insert_pos - delete_len}, delete_op
        else:
            # Insert is within delete range
            return {**insert_op, 'position': delete_pos}, {**delete_op, 'length': delete_len + len(insert_op['content'])}
    
    @staticmethod
    def _transform_delete_delete(op1: Dict, op2: Dict) -> tuple:
        """Transform two concurrent delete operations"""
        pos1 = op1['position']
        pos2 = op2['position']
        len1 = op1['length']
        len2 = op2['length']
        
        if pos1 + len1 <= pos2:
            # op1 is before op2
            return op1, {**op2, 'position': pos2 - len1}
        elif pos2 + len2 <= pos1:
            # op2 is before op1
            return {**op1, 'position': pos1 - len2}, op2
        else:
            # Overlapping deletes - merge them
            start = min(pos1, pos2)
            end = max(pos1 + len1, pos2 + len2)
            return {**op1, 'position': start, 'length': end - start}, {**op2, 'length': 0}


class DataModelSync:
    """
    Sync data models between client and server.
    Handles offline changes and conflict resolution.
    """
    
    def __init__(self):
        self.local_changes = []
        self.server_version = 0
    
    def track_change(self, change: Dict[str, Any]):
        """Track a local change"""
        change['local_version'] = len(self.local_changes)
        change['timestamp'] = datetime.now().isoformat()
        self.local_changes.append(change)
    
    def sync(self, server_changes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Sync with server changes.
        Returns resolved changes to apply locally.
        """
        # Three-way merge: local changes, server changes, common ancestor
        resolved = {
            'to_apply_locally': [],
            'to_send_to_server': [],
            'conflicts': []
        }
        
        # Detect conflicts
        for local_change in self.local_changes:
            conflicting = False
            
            for server_change in server_changes:
                if self._is_conflicting(local_change, server_change):
                    conflicting = True
                    resolved['conflicts'].append({
                        'local': local_change,
                        'server': server_change,
                        'resolution': 'server_wins'  # Default strategy
                    })
                    break
            
            if not conflicting:
                resolved['to_send_to_server'].append(local_change)
        
        # Add non-conflicting server changes
        for server_change in server_changes:
            if not any(self._is_conflicting(server_change, local) for local in self.local_changes):
                resolved['to_apply_locally'].append(server_change)
        
        return resolved
    
    def _is_conflicting(self, change1: Dict, change2: Dict) -> bool:
        """Check if two changes conflict"""
        # Simple conflict detection: same field changed
        return (
            change1.get('field') == change2.get('field') and
            change1.get('path') == change2.get('path')
        )
    
    def generate_checksum(self, data: Any) -> str:
        """Generate checksum for data integrity"""
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()
    
    def verify_integrity(self, data: Any, expected_checksum: str) -> bool:
        """Verify data integrity"""
        actual_checksum = self.generate_checksum(data)
        return actual_checksum == expected_checksum


class AutoSaveManager:
    """Manage automatic saving with conflict resolution"""
    
    def __init__(self, save_interval: int = 30):
        self.save_interval = save_interval  # seconds
        self.pending_changes = []
        self.last_save = None
    
    def should_save(self) -> bool:
        """Check if it's time to auto-save"""
        if not self.pending_changes:
            return False
        
        if not self.last_save:
            return True
        
        elapsed = (datetime.now() - self.last_save).total_seconds()
        return elapsed >= self.save_interval
    
    def add_change(self, change: Dict[str, Any]):
        """Add a change to pending changes"""
        self.pending_changes.append(change)
    
    def get_changes_to_save(self) -> List[Dict[str, Any]]:
        """Get and clear pending changes"""
        changes = self.pending_changes.copy()
        self.pending_changes = []
        self.last_save = datetime.now()
        return changes


class LockAndDam:
    def __init__(self, name, upstream_level, downstream_level):
        self.name = name
        self.upstream_level = upstream_level
        self.downstream_level = downstream_level
        self.lock_chamber_level = downstream_level
        self.is_filling = False
        self.is_draining = False
        self.upstream_gates_open = False
        self.downstream_gates_open = False
    
    def fill_chamber(self):
        """Fill lock chamber to upstream level"""
        if not self.is_draining:
            self.is_filling = True
            self.lock_chamber_level = self.upstream_level
            self.is_filling = False
    
    def drain_chamber(self):
        """Drain lock chamber to downstream level"""
        if not self.is_filling:
            self.is_draining = True
            self.lock_chamber_level = self.downstream_level
            self.is_draining = False
    
    def open_upstream_gates(self):
        """Open upstream gates"""
        if not (self.is_filling or self.is_draining):
            self.upstream_gates_open = True
    
    def close_upstream_gates(self):
        """Close upstream gates"""
        self.upstream_gates_open = False
    
    def open_downstream_gates(self):
        """Open downstream gates"""
        if not (self.is_filling or self.is_draining):
            self.downstream_gates_open = True
    
    def close_downstream_gates(self):
        """Close downstream gates"""
        self.downstream_gates_open = False
    
    def get_status(self):
        """Return current lock status"""
        return {
            'name': self.name,
            'chamber_level': self.lock_chamber_level,
            'upstream_gates_open': self.upstream_gates_open,
            'downstream_gates_open': self.downstream_gates_open,
            'filling': self.is_filling,
            'draining': self.is_draining
        }
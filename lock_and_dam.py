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
        self.fill_rate = 0.4  # m/s

    def fill_chamber(self):
        """Start filling lock chamber to upstream level"""
        if not self.downstream_gates_open:
            self.is_filling = True
            self.is_draining = False

    def drain_chamber(self):
        """Start draining lock chamber to downstream level"""
        if not self.upstream_gates_open:
            self.is_draining = True
            self.is_filling = False

    def update(self, dt):
        """Gradually change water level if filling or draining."""
        if self.is_filling:
            if self.downstream_gates_open:
                self.is_filling = False
            elif self.lock_chamber_level < self.upstream_level:
                self.lock_chamber_level += self.fill_rate * dt
                if self.lock_chamber_level >= self.upstream_level:
                    self.lock_chamber_level = self.upstream_level
                    self.is_filling = False
            else:
                self.is_filling = False

        if self.is_draining:
            if self.upstream_gates_open:
                self.is_draining = False
            elif self.lock_chamber_level > self.downstream_level:
                self.lock_chamber_level -= self.fill_rate * dt
                if self.lock_chamber_level <= self.downstream_level:
                    self.lock_chamber_level = self.downstream_level
                    self.is_draining = False
            else:
                self.is_draining = False
    
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
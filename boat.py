class Boat:
    def __init__(self, name, length, beam, draft, vessel_type):
        self.name = name
        self.length = length  # meters
        self.beam = beam      # meters
        self.draft = draft    # meters
        self.vessel_type = vessel_type
        self.speed = 0
        self.position = 0
    
    def can_fit_in_lock(self, lock_length, lock_width, lock_depth):
        """Check if boat can fit in lock chamber"""
        return (self.length < lock_length and 
                self.beam < lock_width and 
                self.draft < lock_depth)
    
    def set_speed(self, speed):
        """Set boat speed in knots"""
        self.speed = speed
    
    def move(self, distance):
        """Move boat by distance"""
        self.position += distance
    
    def get_bounds(self):
        """Get boat boundaries for collision detection"""
        return (self.position, self.position + self.length)
    
    def check_collision(self, other_boat):
        """Check if this boat collides with another boat"""
        self_start, self_end = self.get_bounds()
        other_start, other_end = other_boat.get_bounds()
        return not (self_end <= other_start or self_start >= other_end)

# Specific boat types
class Kayak(Boat):
    def __init__(self, name):
        super().__init__(name, 4, 0.6, 0.3, "kayak")

class Yacht(Boat):
    def __init__(self, name, length=15):
        super().__init__(name, length, 4, 2, "yacht")

class Barge(Boat):
    def __init__(self, name, length=60):
        super().__init__(name, length, 10, 3, "barge")

class ContainerShip(Boat):
    def __init__(self, name, length=300):
        super().__init__(name, length, 45, 15, "container_ship")
class Waterway:
    def __init__(self, name, length, width, depth, waterway_type):
        self.name = name
        self.length = length  # kilometers
        self.width = width    # meters
        self.depth = depth    # meters
        self.waterway_type = waterway_type
        self.boats = []
        self.current_speed = 0  # m/s
    
    def add_boat(self, boat):
        """Add boat to waterway"""
        self.boats.append(boat)
    
    def remove_boat(self, boat):
        """Remove boat from waterway"""
        if boat in self.boats:
            self.boats.remove(boat)
    
    def can_accommodate(self, boat):
        """Check if waterway can accommodate boat"""
        return boat.beam < self.width and boat.draft < self.depth
    
    def set_current(self, speed):
        """Set water current speed"""
        self.current_speed = speed

class Canal(Waterway):
    def __init__(self, name, length=50, width=30, depth=4):
        super().__init__(name, length, width, depth, "canal")

class River(Waterway):
    def __init__(self, name, length=200, width=100, depth=10):
        super().__init__(name, length, width, depth, "river")
        self.current_speed = 1.5  # rivers typically have current
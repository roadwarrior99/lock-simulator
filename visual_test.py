import matplotlib.pyplot as plt
import matplotlib.patches as patches
import lock_and_dam
import boat
import waterway

def draw_shore_view(lock_dam, waterway, boats):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Top-down view
    ax1.add_patch(patches.Rectangle((0, 0), 100, 30, fill=False))  # Lock chamber
    ax1.add_patch(patches.Rectangle((-50, 0), 50, 30, alpha=0.3))  # Upstream
    ax1.add_patch(patches.Rectangle((100, 0), 50, 30, alpha=0.3))  # Downstream
    
    # Draw boats as rectangles
    for i, boat in enumerate(boats):
        ax1.add_patch(patches.Rectangle((boat.position, 10), boat.length, boat.beam))
    
    ax1.set_xlim(-60, 160)
    ax1.set_ylim(-5, 35)
    ax1.set_title("Top-down View")
    
    # Side view
    ax2.add_patch(patches.Rectangle((0, lock_dam.downstream_level), 100, 
                                   lock_dam.upstream_level - lock_dam.downstream_level))
    ax2.set_title("Side View")

def draw_boat_view(boat, surrounding_boats):
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Draw water horizon
    ax.axhline(y=0, color='blue', alpha=0.3, linewidth=20)
    
    # Draw other boats relative to viewer
    for other_boat in surrounding_boats:
        distance = abs(other_boat.position - boat.position)
        if distance < 200:  # Only show nearby boats
            scale = max(0.1, 1 - distance/200)  # Perspective scaling
            ax.add_patch(patches.Rectangle((other_boat.position - boat.position, 0), 
                                         other_boat.length * scale, 10 * scale))
    
    ax.set_xlim(-100, 100)
    ax.set_ylim(-10, 30)
    ax.set_title(f"View from {boat.name}")

if __name__ == "__main__":
    # Create lock and dam
    lock_dam = lock_and_dam.LockAndDam("Main Lock", upstream_level=10, downstream_level=0)
    
    # Create waterway
    canal = waterway.Canal("Main Canal")
    
    # Create boats
    boat1 = boat.Yacht("Yacht A", length=15)
    boat2 = boat.Barge("Barge B", length=60)
    boat3 = boat.Kayak("Kayak C")
    
    # Position boats
    boat1.position = 20
    boat2.position = 80
    boat3.position = -30
    
    boats = [boat1, boat2, boat3]
    
    # Draw shore view
    draw_shore_view(lock_dam, canal, boats)
    
    # Draw boat view from Yacht A
    draw_boat_view(boat1, boats)
    
    plt.show()
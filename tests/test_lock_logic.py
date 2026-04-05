import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lock_and_dam import LockAndDam

def test_lock_safety():
    # Setup
    lock = LockAndDam("Test", 10, 0)
    lock.lock_chamber_level = 10
    
    # 1. Try to drain when upstream is open
    lock.upstream_gates_open = True
    lock.drain_chamber()
    assert not lock.is_draining, "Should NOT start draining when upstream gate is open"
    
    # 2. Try to drain when upstream is closed
    lock.upstream_gates_open = False
    lock.drain_chamber()
    assert lock.is_draining, "Should start draining when upstream gate is closed"
    
    # 3. Open upstream gate while draining
    lock.upstream_gates_open = True
    lock.update(1.0)
    assert not lock.is_draining, "Should STOP draining if upstream gate is opened"
    
    # 4. Try to fill when downstream is open
    lock.lock_chamber_level = 0
    lock.downstream_gates_open = True
    lock.fill_chamber()
    assert not lock.is_filling, "Should NOT start filling when downstream gate is open"
    
    # 5. Try to fill when downstream is closed
    lock.downstream_gates_open = False
    lock.fill_chamber()
    assert lock.is_filling, "Should start filling when downstream gate is closed"
    
    # 6. Open downstream gate while filling
    lock.downstream_gates_open = True
    lock.update(1.0)
    assert not lock.is_filling, "Should STOP filling if downstream gate is opened"
    
    print("All safety checks passed!")

if __name__ == "__main__":
    test_lock_safety()

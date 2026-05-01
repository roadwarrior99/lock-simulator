"""
Mississippi River Lock and Dam - Blender Python Script

Run this inside Blender's Scripting editor (version 3.x or 4.x).

Structure overview:

- Dam wall with concrete texture via material
- Tainter gates (radial/fan-shaped spillway gates)
- Lock chamber (approach walls, miter gates, valve culverts)
- Control house / operator building
- Guard wall / guide wall
- Bollards, mooring hardware
- River terrain with basic water plane
- Named materials for game-engine export (PBR-ready slots)

All units are in meters. Scale is approximate to a real
Mississippi River navigation lock (~180m x 33m chamber).
"""

import bpy
import bmesh
import math
from mathutils import Vector

# ─── Helpers ──────────────────────────────────────────────────────────────────

def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)

def new_collection(name, parent=None):
    col = bpy.data.collections.new(name)
    if parent:
        parent.children.link(col)
    else:
        bpy.context.scene.collection.children.link(col)
    return col

def link(obj, col):
    col.objects.link(obj)
    if obj.name in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.unlink(obj)

def box(name, loc, size, col, mat=None):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (size[0]/2, size[1]/2, size[2]/2)
    bpy.ops.object.transform_apply(scale=True)
    if mat:
        obj.data.materials.append(mat)
    link(obj, col)
    return obj

def cylinder(name, loc, radius, depth, col, mat=None, verts=16):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=verts, radius=radius, depth=depth, location=loc)
    obj = bpy.context.object
    obj.name = name
    if mat:
        obj.data.materials.append(mat)
    link(obj, col)
    return obj

# ─── Materials (PBR-ready, game-engine friendly) ──────────────────────────────

def make_material(name, base_color, roughness=0.8, metallic=0.0):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat

def setup_materials():
    mats = {}
    mats["concrete"]     = make_material("M_Concrete",     (0.55, 0.53, 0.50), roughness=0.90)
    mats["concrete_dark"]= make_material("M_ConcreteDark", (0.35, 0.34, 0.32), roughness=0.92)
    mats["steel"]        = make_material("M_Steel",        (0.40, 0.42, 0.45), roughness=0.45, metallic=0.90)
    mats["steel_paint"]  = make_material("M_SteelPaint",   (0.13, 0.29, 0.47), roughness=0.55, metallic=0.10)
    mats["water"]        = make_material("M_Water",        (0.05, 0.18, 0.28), roughness=0.05, metallic=0.0)
    mats["earth"]        = make_material("M_Earth",        (0.28, 0.22, 0.15), roughness=0.95)
    mats["building"]     = make_material("M_Building",     (0.60, 0.58, 0.54), roughness=0.85)
    mats["roof"]         = make_material("M_Roof",         (0.20, 0.22, 0.24), roughness=0.80)
    mats["railing"]      = make_material("M_Railing",      (0.70, 0.68, 0.65), roughness=0.50, metallic=0.60)
    mats["gate"]         = make_material("M_Gate",         (0.16, 0.36, 0.20), roughness=0.55, metallic=0.20)
    return mats

# ─── River Terrain ────────────────────────────────────────────────────────────

def build_terrain(col, mats):
    """Flat earth bank on both sides + water plane."""
    # Upstream water
    box("Water_Upstream", (0, -120, -0.1), (80, 120, 0.4), col, mats["water"])
    # Downstream water
    box("Water_Downstream", (0, 120, -1.6), (80, 120, 0.4), col, mats["water"])
    # North bank
    box("Bank_North", (0, -200, -1), (200, 80, 3), col, mats["earth"])
    # South bank
    box("Bank_South", (0, 200, -1), (200, 80, 3), col, mats["earth"])
    # River bed
    box("Riverbed", (0, 0, -3), (80, 500, 2), col, mats["earth"])

# ─── Dam Wall & Spillway ──────────────────────────────────────────────────────

def build_dam_wall(col, mats):
    """
    Concrete gravity dam wall running east-west (X axis).
    Spillway bays in the middle, solid abutments on each side.
    """
    # Main dam sill / base (full width)
    box("Dam_Base", (0, 0, -1.5), (80, 12, 5), col, mats["concrete"])

    # Solid west abutment
    box("Dam_Abutment_W", (-30, 0, 2.5), (20, 12, 9), col, mats["concrete"])
    # Solid east abutment (lock-side)
    box("Dam_Abutment_E", (30, 0, 2.5), (20, 12, 9), col, mats["concrete"])

    # Spillway piers between Tainter gates (4 gates → 3 interior piers + 2 end piers)
    pier_xs = [-12, -4, 4, 12]
    for i, px in enumerate(pier_xs):
        box(f"SpillPier_{i}", (px, 0, 3), (2, 12, 11), col, mats["concrete_dark"])

    # Bridge deck / walkway over dam
    box("Dam_BridgeDeck", (0, 0, 8), (80, 3, 0.5), col, mats["concrete"])

    return pier_xs

def build_tainter_gates(col, mats, pier_xs):
    """
    Tainter (radial) gates: curved steel plates that rotate on a trunnion.
    Approximated with a fan of rectangular faces forming an arc.
    """
    gate_centers = [-16, -8, 0, 8]   # midpoints between piers
    radius = 7.0
    angle_start = math.radians(-30)
    angle_end   = math.radians(60)
    n_segments  = 8

    for gi, gx in enumerate(gate_centers):
        mesh = bpy.data.meshes.new(f"TainterGate_{gi}_Mesh")
        obj  = bpy.data.objects.new(f"TainterGate_{gi}", mesh)
        col.objects.link(obj)

        bm = bmesh.new()
        trunnion = Vector((gx, -2.0, 7.5))  # pivot point (trunnion hub)

        prev_verts = None
        for s in range(n_segments + 1):
            t = s / n_segments
            angle = angle_start + t * (angle_end - angle_start)
            dx = math.sin(angle) * radius
            dz = -math.cos(angle) * radius
            v_front = bm.verts.new(trunnion + Vector((0, -2.5 + dx*0, dz)) + Vector((0, -2, 0)))
            v_back  = bm.verts.new(trunnion + Vector((0,  2.5 + dx*0, dz)) + Vector((0,  2, 0)))
            # Use angle to offset Y for the arc shape
            yf = -2.5 + math.cos(angle) * 1.5
            yb =  2.5 + math.cos(angle) * 1.5
            v_front.co = trunnion + Vector((0, yf, dz))
            v_back.co  = trunnion + Vector((0, yb, dz))
            if prev_verts:
                bm.faces.new([prev_verts[0], prev_verts[1], v_back, v_front])
            prev_verts = [v_front, v_back]

        bm.to_mesh(mesh)
        bm.free()
        mesh.calc_normals()
        obj.data.materials.append(mats["gate"])

# ─── Lock Chamber ─────────────────────────────────────────────────────────────

LOCK_W   = 33    # standard Mississippi navigation lock width (ft ~110 → 33m)
LOCK_L   = 183   # lock chamber length (600 ft ≈ 183m)
WALL_T   = 4     # wall thickness
WALL_H   = 10    # wall height above sill
SILL_Z   = -1.0  # lock floor elevation

def build_lock_chamber(col, mats):
    """Monolithic concrete lock walls, floor, and culvert details."""
    # Lock floor
    box("Lock_Floor", (0, 60, SILL_Z - 0.25), (LOCK_W, LOCK_L, 0.5), col, mats["concrete_dark"])

    # West wall
    box("Lock_Wall_W",
        (-(LOCK_W/2 + WALL_T/2), 60, SILL_Z + WALL_H/2),
        (WALL_T, LOCK_L, WALL_H),
        col, mats["concrete"])

    # East wall
    box("Lock_Wall_E",
        ( (LOCK_W/2 + WALL_T/2), 60, SILL_Z + WALL_H/2),
        (WALL_T, LOCK_L, WALL_H),
        col, mats["concrete"])

    # Upper guard wall (upstream approach)
    box("GuardWall_Upper_W", (-(LOCK_W/2 + WALL_T/2), -30, SILL_Z + 3), (WALL_T, 60, 6), col, mats["concrete"])
    box("GuardWall_Upper_E", ( (LOCK_W/2 + WALL_T/2), -30, SILL_Z + 3), (WALL_T, 60, 6), col, mats["concrete"])

    # Lower guard wall (downstream approach)
    box("GuardWall_Lower_W", (-(LOCK_W/2 + WALL_T/2), 145, SILL_Z + 3), (WALL_T, 50, 6), col, mats["concrete"])
    box("GuardWall_Lower_E", ( (LOCK_W/2 + WALL_T/2), 145, SILL_Z + 3), (WALL_T, 50, 6), col, mats["concrete"])

    # Valve culvert openings (decorative boxes at base of walls)
    for side_x in [-(LOCK_W/2 + WALL_T*0.5), (LOCK_W/2 + WALL_T*0.5)]:
        for cy in [30, 50, 70, 90]:
            box(f"Culvert_{side_x:.0f}_{cy}", (side_x, cy, SILL_Z + 1), (1.0, 2.0, 1.5), col, mats["concrete_dark"])

def build_miter_gates(col, mats):
    """
    Miter gates: two leaves that meet in a V pointing upstream.
    Built at both ends of the lock chamber.
    """
    gate_sets = [
        ("Upper", 0,   -1),   # upstream end, V points upstream (negative Y)
        ("Lower", 120,  1),   # downstream end, V points downstream
    ]
    leaf_w = LOCK_W / 2 + 0.5
    leaf_h = WALL_H - 0.5
    leaf_t = 0.6
    miter_angle = math.radians(17)   # angle of each leaf from perpendicular

    for label, gate_y, sign in gate_sets:
        for side, sx in [("L", -(LOCK_W/4)), ("R", (LOCK_W/4))]:
            name = f"MiterGate_{label}_{side}"
            bpy.ops.mesh.primitive_cube_add(
                location=(sx, gate_y + sign * math.sin(miter_angle) * leaf_w * 0.5,
                           SILL_Z + leaf_h / 2))
            obj = bpy.context.object
            obj.name = name
            obj.scale = (leaf_w / 2, leaf_t / 2, leaf_h / 2)
            # Rotate leaf to miter angle
            obj.rotation_euler.z = sign * miter_angle * (1 if side == "L" else -1)
            bpy.ops.object.transform_apply(scale=True, rotation=True)
            obj.data.materials.append(mats["steel_paint"])
            link(obj, col)

        # Horizontal ribbing on gates (structural stiffeners)
        for side, sx in [("L", -(LOCK_W/4)), ("R", (LOCK_W/4))]:
            for ri in range(4):
                rz = SILL_Z + 1.5 + ri * (leaf_h / 4)
                rib = box(f"GateRib_{label}_{side}_{ri}",
                          (sx, gate_y, rz),
                          (leaf_w, leaf_t + 0.3, 0.25),
                          col, mats["steel"])

# ─── Control House ────────────────────────────────────────────────────────────

def build_control_house(col, mats):
    """Operator control building on the east lock wall."""
    bx = LOCK_W / 2 + WALL_T + 4
    by = 55

    # Foundation
    box("CtrlHouse_Foundation", (bx, by, 1.0), (10, 12, 2.5), col, mats["concrete"])
    # Walls
    box("CtrlHouse_Walls", (bx, by, 5.0), (10, 12, 6), col, mats["building"])
    # Roof (slightly wider)
    box("CtrlHouse_Roof", (bx, by, 8.25), (11, 13, 0.5), col, mats["roof"])
    # Windows (dark recessed boxes)
    for wy in [by - 3, by, by + 3]:
        box(f"CtrlHouse_Win_{wy:.0f}", (bx - 5.1, wy, 5.5), (0.2, 1.5, 1.5), col, mats["concrete_dark"])
    # Control console bump on roof
    box("CtrlHouse_Console", (bx, by, 9.0), (4, 6, 1.5), col, mats["roof"])
    # Antenna mast
    cylinder("CtrlHouse_Antenna", (bx + 3, by + 4, 11), 0.1, 5, col, mats["steel"])

# ─── Machinery & Hardware ─────────────────────────────────────────────────────

def build_machinery(col, mats):
    """Gate operating machinery, bollards, mooring hardware."""

    # Hydraulic cylinder assemblies at miter gate pivots
    gate_ys = [0, 120]
    for gy in gate_ys:
        for sx in [-(LOCK_W/2 + WALL_T), (LOCK_W/2 + WALL_T)]:
            cylinder(f"HydCyl_{gy}_{sx:.0f}",
                     (sx, gy, SILL_Z + WALL_H - 1),
                     0.4, 3.5, col, mats["steel"])
            # Arm connecting cylinder to gate
            box(f"HydArm_{gy}_{sx:.0f}",
                (sx * 0.85, gy, SILL_Z + WALL_H - 1),
                (abs(sx) * 0.3, 0.3, 0.3),
                col, mats["steel"])

    # Bollards along lock walls (mooring posts)
    bollard_ys = list(range(10, 120, 15))
    for by in bollard_ys:
        for sx in [-(LOCK_W/2 + WALL_T + 1), (LOCK_W/2 + WALL_T + 1)]:
            cyl = cylinder(f"Bollard_{by}_{sx:.0f}",
                           (sx, by, SILL_Z + WALL_H + 0.5),
                           0.35, 1.2, col, mats["steel"])
            # Cap disc
            cylinder(f"BollardCap_{by}_{sx:.0f}",
                     (sx, by, SILL_Z + WALL_H + 1.2),
                     0.5, 0.2, col, mats["steel"])

    # Floating mooring bitt on approach walls
    for by in [-25, -15, 135, 145]:
        for sx in [-(LOCK_W/2 + WALL_T + 1), (LOCK_W/2 + WALL_T + 1)]:
            cylinder(f"Bitt_{by}_{sx:.0f}",
                     (sx, by, SILL_Z + 6 + 0.5),
                     0.25, 1.0, col, mats["steel"])

# ─── Railings & Walkways ──────────────────────────────────────────────────────

def build_railings(col, mats):
    """Safety railings along wall tops and bridge deck."""
    top_z = SILL_Z + WALL_H + 0.5
    rail_h = 1.1
    post_spacing = 3.0

    sides = [
        (-(LOCK_W/2 + WALL_T + 0.1), 0, LOCK_L),
        ( (LOCK_W/2 + WALL_T + 0.1), 0, LOCK_L),
    ]
    for (rx, ry_start, ry_len) in sides:
        n_posts = int(ry_len / post_spacing)
        for i in range(n_posts + 1):
            py = ry_start + i * post_spacing
            # Vertical post
            cylinder(f"RailPost_{rx:.0f}_{i}",
                     (rx, py, top_z + rail_h / 2),
                     0.05, rail_h, col, mats["railing"], verts=8)
        # Horizontal top rail (one long box)
        box(f"TopRail_{rx:.0f}",
            (rx, ry_start + ry_len / 2, top_z + rail_h),
            (0.08, ry_len, 0.08),
            col, mats["railing"])
        # Mid rail
        box(f"MidRail_{rx:.0f}",
            (rx, ry_start + ry_len / 2, top_z + rail_h * 0.5),
            (0.08, ry_len, 0.08),
            col, mats["railing"])

# ─── Navigation Lights ───────────────────────────────────────────────────────

def build_nav_lights(col, mats):
    """Red/green navigation lights at lock entrance."""
    light_mat_r = make_material("M_NavRed",   (0.9, 0.05, 0.05), roughness=0.3)
    light_mat_g = make_material("M_NavGreen", (0.05, 0.8, 0.15), roughness=0.3)

    # Upstream entrance lights
    for (lx, lmat, lname) in [
        (-(LOCK_W/2 + 1), light_mat_r, "NavLight_Red_Up"),
        ( (LOCK_W/2 + 1), light_mat_g, "NavLight_Grn_Up"),
    ]:
        pole = cylinder(lname + "_Pole", (lx, -2, SILL_Z + WALL_H + 2), 0.1, 7, col, mats["steel"])
        lamp = cylinder(lname + "_Lamp", (lx, -2, SILL_Z + WALL_H + 5.5), 0.3, 0.5, col, lmat)

    # Downstream
    for (lx, lmat, lname) in [
        (-(LOCK_W/2 + 1), light_mat_r, "NavLight_Red_Dn"),
        ( (LOCK_W/2 + 1), light_mat_g, "NavLight_Grn_Dn"),
    ]:
        pole = cylinder(lname + "_Pole", (lx, 122, SILL_Z + WALL_H + 2), 0.1, 7, col, mats["steel"])
        lamp = cylinder(lname + "_Lamp", (lx, 122, SILL_Z + WALL_H + 5.5), 0.3, 0.5, col, lmat)

# ─── Camera & Lighting Setup ─────────────────────────────────────────────────

def setup_scene():
    # Sun lamp
    bpy.ops.object.light_add(type='SUN', location=(50, -50, 80))
    sun = bpy.context.object
    sun.name = "Sun"
    sun.data.energy = 5.0
    sun.rotation_euler = (math.radians(45), 0, math.radians(30))

    # Camera for overview
    bpy.ops.object.camera_add(location=(120, -180, 90))
    cam = bpy.context.object
    cam.name = "OverviewCam"
    cam.rotation_euler = (math.radians(55), 0, math.radians(40))
    bpy.context.scene.camera = cam

    # World background (sky blue)
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.38, 0.60, 0.85, 1.0)
        bg.inputs["Strength"].default_value = 1.0

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=== Building Mississippi River Lock & Dam ===")
    clear_scene()

    # Collections
    root = new_collection("LockAndDam")
    col_terrain  = new_collection("Terrain",    root)
    col_dam      = new_collection("Dam",        root)
    col_lock     = new_collection("Lock",       root)
    col_mech     = new_collection("Machinery",  root)
    col_arch     = new_collection("Architecture", root)

    mats = setup_materials()

    print("  Building terrain...")
    build_terrain(col_terrain, mats)

    print("  Building dam wall...")
    pier_xs = build_dam_wall(col_dam, mats)

    print("  Building Tainter gates...")
    build_tainter_gates(col_dam, mats, pier_xs)

    print("  Building lock chamber...")
    build_lock_chamber(col_lock, mats)

    print("  Building miter gates...")
    build_miter_gates(col_lock, mats)

    print("  Building control house...")
    build_control_house(col_arch, mats)

    print("  Building machinery & bollards...")
    build_machinery(col_mech, mats)

    print("  Building railings...")
    build_railings(col_arch, mats)

    print("  Building navigation lights...")
    build_nav_lights(col_arch, mats)

    print("  Setting up scene...")
    setup_scene()

    print("=== Done! Lock & Dam built successfully. ===")
    print("Collections: Terrain / Dam / Lock / Machinery / Architecture")
    print("All objects have PBR materials assigned.")
    print("Next steps:")
    print("  1. Add a Subdivision Surface modifier to walls for smoother edges")
    print("  2. Bake normal maps for concrete/steel in Cycles")
    print("  3. UV-unwrap each collection for texture atlasing")
    print("  4. Export collections separately as .fbx or .glb for your game engine")

main()

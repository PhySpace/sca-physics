"""Small, versioned whole-object starting estimates, never material calibration.

The referenced products bound plausible dimensions/line masses, not EI/GJ.
All stiffness, loss and contact numbers below are explicit engineering estimates.
"""
PRESET_VERSION = "2026.10.1"
RULE_VERSION = "uniform-cable-2"
SOLVER_POLICY_VERSION = "bounded-initial-1"

PRESETS = {
    "stranded_wire": {
        "label": "ordinary stranded flexible PVC-insulated single-core wire",
        "reference_diameter_m": .0026, "reference_linear_density_kg_m": .015,
        "bending_rigidity_Nm2": 5e-4, "torsional_rigidity_Nm2": 1.5e-4,
        "joint_damping_Nms_rad": 1e-7, "diameters_per_segment": 8., "gravity_length_fraction": .5,
        "minimum_bend_radius_diameters": 6., "static_friction": .45, "dynamic_friction": .35,
        "physics_hz": 1200, "diameter_range_m": [.002, .006],
        "reference_url": "https://products.lappgroup.com/online-catalogue/power-and-control-cables/control-cabinet-single-cores/various-applications/h05v-k.html",
        "reference_detail": "H05V-K 1mm2 catalog: OD2.4..2.8mm, nominal line mass15kg/km. Generic object is assumed similar, not identified as this SKU. Area scaling is an estimate; no pure-copper whole-wire stiffness is used.",
    },
    "pvc_jump_rope": {
        "label": "ordinary PVC jump-rope cord with an inner string core; handles are separate CAD bodies",
        "reference_diameter_m": .005, "reference_linear_density_kg_m": .021985,
        "bending_rigidity_Nm2": 3e-4, "torsional_rigidity_Nm2": 2e-4,
        "joint_damping_Nms_rad": 5e-7, "diameters_per_segment": 12., "gravity_length_fraction": .8,
        "minimum_bend_radius_diameters": 3., "static_friction": .5, "dynamic_friction": .4,
        "physics_hz": 960, "diameter_range_m": [.004, .006],
        "reference_url": "https://elitejumps.co/collections/jump-rope-teams/products/pvc-replacement-cords",
        "reference_detail": "5mm replacement PVC cord with an inner string core, 11ft/2.6oz gives about21.985g/m; small retaining hardware may be included. Whole-cord equivalent attributes and diameter-squared scaling are estimates, not a homogeneous PVC density or calibrated rope.",
    },
}

QUALITY = {
    "preview": {"minimum_segments": 12, "length_factor": 1.5, "turn_degrees": 20., "sagitta_diameters": .5,
                "frequency_factor": .75, "position_iterations": 32, "velocity_iterations": 2},
    "balanced": {"minimum_segments": 20, "length_factor": 1., "turn_degrees": 15., "sagitta_diameters": .25,
                 "frequency_factor": 1., "position_iterations": 64, "velocity_iterations": 4},
    "fine": {"minimum_segments": 32, "length_factor": .65, "turn_degrees": 10., "sagitta_diameters": .1,
             "frequency_factor": 2., "position_iterations": 96, "velocity_iterations": 4},
}

# Resource protections, not backend maxima or a guarantee of simulation speed.
DEFAULT_RESOURCE_BUDGET = {
    "max_bodies": 256, "max_joints": 256, "max_colliders": 256,
    "max_filtered_pairs": 4096, "max_contact_pairs": 32768,
    "max_solver_work_per_second": 80_000_000,
}

LIMITATIONS = [
    "Category values are initial whole-object presets/engineering estimates, not a measurement of the described object.",
    "Translation-locked D6 models an inextensible chain; finite tensile compliance/EA is not implemented or authored.",
    "Planar initial centerlines, straight natural reference, circular proxies and per-joint damping only; no spatial natural curve or continuous distributed damping.",
    "Per-joint damping and capsule inertia do not establish dynamic subdivision equivalence.",
    "The initial solver policy is budgeted and requires application-specific checks; it does not certify stiffness/torsion accuracy. rc2 strict static limitations remain.",
    "Uniform sampling uses available initial polyline curvature; insufficiently sampled CAD curves and future contact demands are not inferred exactly.",
]

# Focused stable-maintenance acceptance fixture

This is a small acceptance fixture, not a new demonstration assembly. Native SCA
creates one aluminium cube definition and eight independent occurrences. All
dimensions and placements are millimetres, with +Z up. The cube is 10 x 10 x 10,
volume 1000 mm^3, with native density 2700 kg/m^3 (nominal, not measured).

Only `anchor` is grounded by the native assembly. Other occurrences have no
constraints. Their origins are spaced 500 mm along X at Z=300 mm to prevent
contacts during the half-second rigid-body test. All physics additions follow
the stable inspect/template -> enrich -> validate -> export workflow. The
fixture distinguishes static, dynamic, kinematic, per-instance gravity and
damping, signed rest offset, and independent contact materials. No robotics,
drives, advanced schemas, authoring context, or unified save interface is used.

Copy these two notebooks to a fresh results directory before running them, so
SCA-generated notebook state remains outside the maintained source tree.

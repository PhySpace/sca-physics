# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi==2.2.5"]
#
# [tool.simplecadapi]
# id = "pendulum_arm"
# revision = "1.0.0"
# ///
"""Aluminium pendulum arm, 100 x 10 x 10 mm, connector at one end."""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- feature: arm-bar (build) ----
    # This design is exactly a rectangular primitive, X ranges from 0 to 100.
    arm_bar = scad.make_box_rsolid(
        width=100.0, height=10.0, depth=10.0,
        bottom_face_center=(50.0, 0.0, -5.0),
    )
    return (arm_bar,)


@app.cell
def _(arm_bar):
    # ---- feature: material-and-hinge (annotate) ----
    _part = scad.make_part_rpart(part_id="pendulum_arm", body=arm_bar)
    _aluminium = scad.make_material_rmaterial(
        material_id="aluminium", name="Aluminium (nominal density)",
        density=2.7e-6, density_unit="kg/mm^3", color=(0.8, 0.4, 0.15),
    )
    _part = scad.assign_material_rpart(part=_part, material=_aluminium)
    pendulum_arm = scad.add_connector_rpart(
        part=_part,
        connector=scad.make_placement_connector_rconnector(
            connector_id="hinge_axis",
            placement=scad.make_placement_rplacement(
                origin=(0.0, 0.0, 0.0),
                x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 0.0, -1.0),
            ),
        ),
    )
    return (pendulum_arm,)


if __name__ == "__main__":
    app.run()

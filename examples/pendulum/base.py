# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi==2.2.5"]
#
# [tool.simplecadapi]
# id = "pendulum_base"
# revision = "1.0.0"
# ///
"""Fixed steel pedestal, dimensions in mm; hinge's local Z is global +Y."""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- feature: pedestal (build) ----
    # This design is exactly a rectangular primitive.
    pedestal = scad.make_box_rsolid(width=24.0, height=24.0, depth=80.0)
    return (pedestal,)


@app.cell
def _(pedestal):
    # ---- feature: material-and-hinge (annotate) ----
    _part = scad.make_part_rpart(part_id="pendulum_base", body=pedestal)
    _steel = scad.make_material_rmaterial(
        material_id="steel", name="Steel (nominal density)",
        density=7.85e-6, density_unit="kg/mm^3", color=(0.3, 0.35, 0.4),
    )
    _part = scad.assign_material_rpart(part=_part, material=_steel)
    pendulum_base = scad.add_connector_rpart(
        part=_part,
        connector=scad.make_placement_connector_rconnector(
            connector_id="hinge_axis",
            placement=scad.make_placement_rplacement(
                origin=(0.0, 0.0, 75.0),
                x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 0.0, -1.0),
            ),
        ),
    )
    return (pendulum_base,)


if __name__ == "__main__":
    app.run()

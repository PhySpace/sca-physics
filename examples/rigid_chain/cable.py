# /// script
# requires-python = ">=3.12"
# dependencies = ["simplecadapi==2.2.5"]
#
# [tool.simplecadapi]
# id = "round_cable"
# revision = "1.0.0"
# ///
"""250 mm x 4 mm native CAD cable; mechanical inputs live in chain.json."""
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- feature: round-cable (build) ----
    cable_solid = scad.make_cylinder_rsolid(
        radius=2.0, height=250.0, bottom_face_center=(0.0, 0.0, 100.0),
        axis=(1.0, 0.0, 0.0),
    )
    return (cable_solid,)


@app.cell
def _(cable_solid):
    # ---- feature: nominal-material (annotate) ----
    _part = scad.make_part_rpart(part_id="round_cable", body=cable_solid)
    _material = scad.make_material_rmaterial(
        material_id="nominal_polymer", name="Software demonstration material",
        density=1.2e-6, density_unit="kg/mm^3", color=(0.12, 0.14, 0.17),
    )
    cable = scad.assign_material_rpart(part=_part, material=_material)
    return (cable,)


if __name__ == "__main__":
    app.run()

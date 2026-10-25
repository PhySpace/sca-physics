# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi==2.2.5"]
#
# [tool.simplecadapi]
# id = "mechanical_cube"
# revision = "1.0.0"
# ///
"""One real native SCA solid; dimensions mm, density kg/mm^3."""
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- feature: cube (build) ----
    body = scad.make_box_rsolid(width=10.0, height=10.0, depth=10.0)
    return (body,)


@app.cell
def _(body):
    # ---- feature: native-material (annotate) ----
    _part = scad.make_part_rpart(part_id="mechanical_cube", body=body)
    _material = scad.make_material_rmaterial(
        material_id="nominal_aluminium", name="Aluminium, nominal density",
        density=2.7e-6, density_unit="kg/mm^3", color=(0.51, 0.59, 0.65),
    )
    cube = scad.assign_material_rpart(part=_part, material=_material)
    return (cube,)


if __name__ == "__main__":
    app.run()

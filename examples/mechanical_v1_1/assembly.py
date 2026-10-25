# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi==2.2.5"]
#
# [tool.simplecadapi]
# id = "mechanical_acceptance"
# revision = "1.0.0"
# ///
"""Shared native definition, eight independent occurrences; mm, +Z up."""
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    cube = scad.use("cube.py")
    return (cube,)


@app.cell
def _(cube):
    _assembly = scad.make_assembly_rassembly(
        assembly_id="mechanical_acceptance", name="Stable 0.1.1 acceptance",
    )
    for _index, _role in enumerate((
        "anchor", "static", "dynamic", "kinematic", "gravity_off",
        "linear_damped", "angular_damped", "control",
    )):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly, item=cube, component_id=_role,
            placement=scad.make_placement_rplacement(
                origin=(-1000.0 + 500.0 * _index, 0.0, 300.0),
            ),
        )
    mechanical_acceptance = scad.ground_component_rassembly(
        assembly=_assembly, component_id="anchor",
    )
    return (mechanical_acceptance,)


if __name__ == "__main__":
    app.run()

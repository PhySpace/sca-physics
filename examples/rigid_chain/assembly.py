# /// script
# requires-python = ">=3.12"
# dependencies = ["simplecadapi==2.2.5"]
#
# [tool.simplecadapi]
# id = "round_cable_demo"
# revision = "1.0.0"
# ///
"""Minimal native CAD assembly. Generic physical construction is in plugins."""
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    cable = scad.use("cable.py")
    return (cable,)


@app.cell
def _(cable):
    _assembly = scad.make_assembly_rassembly(
        assembly_id="round_cable_demo", name="Round cable rigid-chain example",
    )
    round_cable_demo = scad.add_component_rassembly(
        assembly=_assembly, item=cable, component_id="wire",
        placement=scad.identity_placement_rplacement(),
    )
    return (round_cable_demo,)


if __name__ == "__main__":
    app.run()

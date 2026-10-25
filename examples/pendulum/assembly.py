# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi==2.2.5"]
#
# [tool.simplecadapi]
# id = "passive_pendulum"
# revision = "1.0.0"
# ///
"""Grounded base + free revolute arm, no motor or position/velocity drive."""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    base = scad.use("base.py")
    arm = scad.use("arm.py")
    return base, arm


@app.cell
def _(base, arm):
    _assembly = scad.make_assembly_rassembly(
        assembly_id="passive_pendulum", name="Passive pendulum verification",
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly, item=base, component_id="base",
        placement=scad.identity_placement_rplacement(),
    )
    _assembly = scad.add_component_rassembly(
        assembly=_assembly, item=arm, component_id="arm",
        placement=scad.make_placement_rplacement(origin=(0.0, 0.0, 75.0)),
    )
    grounded = scad.ground_component_rassembly(
        assembly=_assembly, component_id="base",
    )
    return (grounded,)


@app.cell
def _(grounded):
    jointed = scad.add_revolute_constraint_rassembly(
        assembly=grounded, constraint_id="hinge",
        connector_a=scad.make_connector_ref_rconnectorref("base", "hinge_axis"),
        connector_b=scad.make_connector_ref_rconnectorref("arm", "hinge_axis"),
    )
    return (jointed,)


@app.cell
def _(jointed):
    passive_pendulum = scad.solve_assembly_constraints_rassembly(assembly=jointed)
    return (passive_pendulum,)


if __name__ == "__main__":
    app.run()

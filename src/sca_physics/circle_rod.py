"""Public deterministic circular homogeneous-rod conversion, never a solver."""
from .provenance import parameter, derived


def circle_rod(*, diameter_m, density_kg_m3, youngs_modulus_pa, shear_modulus_pa, source=None):
    """Return λ=rho*A, EI=E*pi*d**4/64 and GJ=G*pi*d**4/32 wrappers.

    Inputs are standard SI wrappers or inherit the explicitly provided source.
    This conversion assumes a homogeneous solid circular section. Applicability
    and the truth of supplied material evidence remain the caller's responsibility.
    """
    diameter = parameter(diameter_m, 'm', 'circle_rod.diameter_m', source)
    result = {}
    for argument, value, unit, output, rule in (
        ('density', density_kg_m3, 'kg/m^3', 'linear_density', 'circle-rod-lambda-v1'),
        ('youngs_modulus', youngs_modulus_pa, 'Pa', 'bending_rigidity', 'circle-rod-EI-v1'),
        ('shear_modulus', shear_modulus_pa, 'Pa', 'torsional_rigidity', 'circle-rod-GJ-v1'),
    ):
        item = parameter(value, unit, 'circle_rod.' + argument, source)
        result[output] = derived(rule, {'diameter': diameter, argument: item},
            'Deterministic homogeneous circular-rod conversion; material inputs are not verified or calibrated by this helper')
    return result

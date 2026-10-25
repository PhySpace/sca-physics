"""Strict input provenance and a small, replayable set of SI calculations."""
from copy import deepcopy
import math

KINDS = frozenset({'explicit', 'reference', 'estimated', 'default', 'derived'})
FORMULAS = {
    'circle-rod-lambda-v1': 'lambda = density * pi * diameter^2 / 4',
    'circle-rod-EI-v1': 'EI = youngs_modulus * pi * diameter^4 / 64',
    'circle-rod-GJ-v1': 'GJ = shear_modulus * pi * diameter^4 / 32',
    'density-from-linear-density-area-v1': 'density = linear_density / (pi * diameter^2 / 4)',
    'mm-to-m-v1': 'length_m = length_mm * 0.001',
    'scale-v1': 'value = base * factor',
    'diameter-power-scale-v1': 'value = base * (diameter / reference_diameter)^power * factor',
    'segment-count-v1': 'N = max(2, ceil(length / target_length))',
    'polyline-length-v1': 'length = sum(norm(centerline[i] - centerline[i-1]), i=1..n-1)',
    'polyline-stations-v1': 'stations[0] = 0; stations[i] = stations[i-1] + norm(centerline[i] - centerline[i-1])',
    'difference-v1': 'value = end - start',
}


def _closed(value, fields, path, required=()):
    if not isinstance(value, dict) or set(value) - set(fields) or set(required) - set(value):
        raise ValueError(f'{path}: expected fields {sorted(fields)}, required {sorted(required)}')
    return value


def source(value, path='source'):
    obj = _closed(value, {'kind', 'detail', 'citation', 'conditions', 'derivation'}, path, {'kind', 'detail'})
    if not isinstance(obj['kind'], str) or obj['kind'] not in KINDS:
        raise ValueError(f'{path}.kind: unsupported source kind')
    for key in ('detail', 'citation', 'conditions'):
        if key == 'detail' or obj['kind'] == 'reference' or key in obj:
            if not isinstance(obj.get(key), str) or not obj[key].strip():
                raise ValueError(f'{path}.{key}: expected a nonempty string')
    if obj['kind'] == 'derived':
        calculation(obj.get('derivation'), path + '.derivation')
    elif 'derivation' in obj:
        raise ValueError(f'{path}.derivation: only derived sources have a calculation')
    return deepcopy(obj)


def inherited(obj, fallback=None, path='source'):
    return source(obj['source'], path) if 'source' in obj else deepcopy(fallback)


def parameter(raw, unit, path, fallback=None):
    if isinstance(raw, dict):
        obj = _closed(raw, {'value', 'unit', 'source'}, path, {'value'})
        adopted_source = obj.get('source', fallback)
        result = {'value': deepcopy(obj['value']), 'unit': obj.get('unit', unit)}
    else:
        adopted_source = fallback
        result = {'value': deepcopy(raw), 'unit': unit}
    if adopted_source is None:
        raise ValueError(f'{path}.source: required; provide a field, group or declaration source')
    result['source'] = source(adopted_source, path + '.source')
    if result['unit'] != unit:
        raise ValueError(f'{path}.unit: expected {unit!r}')
    validate_derived(result, path)
    return result


def _number(wrapper, unit, path, *, positive=False):
    item = parameter(wrapper, unit, path)
    value = item['value']
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{path}: expected a finite number')
    if positive and value <= 0:
        raise ValueError(f'{path}: require a positive number')
    return value


def calculation(raw, path='derivation'):
    obj = _closed(raw, {'rule', 'formula', 'inputs'}, path, {'rule', 'formula', 'inputs'})
    inputs = obj['inputs']
    rule = obj['rule']
    if not isinstance(rule, str) or rule not in FORMULAS:
        raise ValueError(f'{path}.rule: unsupported deterministic rule {rule!r}')
    if obj['formula'] != FORMULAS[rule]:
        raise ValueError(f'{path}.formula: must match the supported rule formula')
    circular = {
        'circle-rod-lambda-v1': ('density', 'kg/m^3', 'kg/m', 2, 4),
        'circle-rod-EI-v1': ('youngs_modulus', 'Pa', 'N*m^2', 4, 64),
        'circle-rod-GJ-v1': ('shear_modulus', 'Pa', 'N*m^2', 4, 32),
    }
    if rule in circular:
        name, unit, output_unit, power, denominator = circular[rule]
        _closed(inputs, {'diameter', name}, path + '.inputs', {'diameter', name})
        diameter = _number(inputs['diameter'], 'm', path + '.inputs.diameter', positive=True)
        modulus = _number(inputs[name], unit, path + '.inputs.' + name, positive=True)
        return modulus * math.pi * diameter ** power / denominator, output_unit
    if rule == 'density-from-linear-density-area-v1':
        _closed(inputs, {'linear_density', 'diameter'}, path + '.inputs', {'linear_density', 'diameter'})
        line = _number(inputs['linear_density'], 'kg/m', path + '.inputs.linear_density', positive=True)
        diameter = _number(inputs['diameter'], 'm', path + '.inputs.diameter', positive=True)
        return line / (math.pi * diameter ** 2 / 4), 'kg/m^3'
    if rule == 'mm-to-m-v1':
        _closed(inputs, {'length'}, path + '.inputs', {'length'})
        return _number(inputs['length'], 'mm', path + '.inputs.length') * .001, 'm'
    if rule == 'scale-v1':
        _closed(inputs, {'base', 'factor'}, path + '.inputs', {'base', 'factor'})
        base = inputs['base']
        value = _number(base, base.get('unit'), path + '.inputs.base')
        factor = _number(inputs['factor'], '1', path + '.inputs.factor')
        return value * factor, base['unit']
    if rule == 'diameter-power-scale-v1':
        _closed(inputs, {'base', 'diameter', 'reference_diameter', 'power', 'factor'}, path + '.inputs', {'base','diameter','reference_diameter','power','factor'})
        base=inputs['base']; value=_number(base,base.get('unit'),path+'.inputs.base')
        diameter=_number(inputs['diameter'],'m',path+'.inputs.diameter',positive=True)
        reference=_number(inputs['reference_diameter'],'m',path+'.inputs.reference_diameter',positive=True)
        power=_number(inputs['power'],'count',path+'.inputs.power',positive=True)
        if power not in {2,4}:raise ValueError(path+'.inputs.power: only circular scaling powers2/4 supported')
        factor=_number(inputs['factor'],'1',path+'.inputs.factor',positive=True)
        return value*(diameter/reference)**power*factor,base['unit']
    if rule == 'segment-count-v1':
        _closed(inputs, {'length', 'target_length'}, path + '.inputs', {'length', 'target_length'})
        length = _number(inputs['length'], 'm', path + '.inputs.length', positive=True)
        target = _number(inputs['target_length'], 'm', path + '.inputs.target_length', positive=True)
        return max(2, math.ceil(length / target)), 'count'
    if rule in {'polyline-length-v1', 'polyline-stations-v1'}:
        _closed(inputs, {'centerline'}, path + '.inputs', {'centerline'})
        item = parameter(inputs['centerline'], 'm', path + '.inputs.centerline')
        points = item['value']
        if not isinstance(points, list) or len(points) < 2 or any(not isinstance(p, list) or len(p) != 3 for p in points):
            raise ValueError(path + ': require a 3D polyline')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for p in points for x in p):
            raise ValueError(path + ': require finite coordinates')
        stations = [0.]
        for a, b in zip(points, points[1:]):
            stations.append(stations[-1] + math.dist(a, b))
        return (stations if rule == 'polyline-stations-v1' else stations[-1]), 'm'
    if rule == 'difference-v1':
        _closed(inputs, {'end', 'start'}, path + '.inputs', {'end', 'start'})
        unit = inputs['end']['unit']
        return _number(inputs['end'], unit, path + '.inputs.end') - _number(inputs['start'], unit, path + '.inputs.start'), unit
    raise ValueError(f'{path}.rule: unsupported deterministic rule {rule!r}')


def validate_derived(wrapper, path='parameter'):
    if wrapper['source']['kind'] != 'derived':
        return
    expected, unit = calculation(wrapper['source']['derivation'], path + '.source.derivation')
    actual = wrapper['value']
    def equal(a, b):
        if isinstance(b, list):
            return isinstance(a, list) and len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        return not isinstance(a, bool) and isinstance(a, (int, float)) and math.isfinite(a) and math.isclose(a, b, rel_tol=1e-12, abs_tol=0)
    if wrapper['unit'] != unit or not equal(actual, expected):
        raise ValueError(path + ': derived value/unit disagree with supported calculation')


def derived(rule, inputs, detail):
    proof = {'rule': rule, 'formula': FORMULAS.get(rule), 'inputs': deepcopy(inputs)}
    value, unit = calculation(proof)
    return {'value': value, 'unit': unit, 'source': {'kind': 'derived', 'detail': detail,
        'derivation': proof}}


def validate_tree(value, *, legacy=False, path='sca_physics'):
    if isinstance(value, dict):
        if {'value', 'unit', 'source'} <= value.keys():
            source(value['source'], path + '.source')
            validate_derived(value, path)
        if 'kind' in value and 'detail' in value and value['kind'] == 'derived' and legacy:
            raise ValueError(path + ': derived source requires schema 1.7; legacy snapshots are not rewritten')
        for key, child in value.items():
            validate_tree(child, legacy=legacy, path=path + '.' + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_tree(child, legacy=legacy, path=f'{path}[{index}]')


def protect_explicit(previous, current, path='sca_physics'):
    """An Agent estimate cannot replace a saved user-authoritative parameter.

    Compare corresponding fields only: explicit representation-conversion flags
    remain responsible for removing a representation's incompatible fields.
    Reading a historical snapshot does not call this update-only check.
    """
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return
    if 'representation' in previous and 'representation' in current and previous['representation'] != current['representation']:
        return  # Explicit representation conversion has a different parameter contract.
    if {'unit', 'source'} <= previous.keys() and ('value' in previous or 'mode' in previous):
        def user_authority(item):
            origin = item.get('source', {})
            if not isinstance(origin, dict):
                return False
            if origin.get('kind') == 'explicit':
                return True
            # Equivalent density and lambda are one mass-parameter family.
            # Only this verified conversion inherits the submitted user's
            # density authority; arbitrary derived inputs are not a bypass.
            proof = origin.get('derivation', {})
            return (path.endswith('.mechanics.linear_density') and origin.get('kind') == 'derived'
                    and proof.get('rule') == 'circle-rod-lambda-v1'
                    and proof.get('inputs', {}).get('density', {}).get('source', {}).get('kind') == 'explicit')
        if user_authority(previous) and current != previous:
            if not user_authority(current):
                raise ValueError(path + ': a saved explicit user parameter requires a new explicit user source to replace it')
        return
    for key in previous.keys() & current.keys():
        protect_explicit(previous[key], current[key], path + '.' + key)

"""Read actual evaluated CAD cylinders, or bind an explicitly supplied polyline.

General centerline reconstruction from an arbitrary BREP is deliberately absent.
"""
import math
from .contract import _closed, _float32
from .deformable import _definitions, geometry_source_snapshot


def _positive(value, path, *, zero=False):
    _float32(value, path)
    if value < 0 or (value == 0 and not zero):
        raise ValueError(f"{path}: expected a finite {'nonnegative' if zero else 'positive'} SI number")
    return float(value)


def _world(point, transform):
    return [sum(transform[i][j] * point[j] * .001 for j in range(3)) + transform[i][3] for i in range(3)]


def read_cylinder(package, target):
    """Accept only a complete solid circular cylinder with two planar caps."""
    from simplecadapi.artifacts.brep import read_brep_shape
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    binding = geometry_source_snapshot(package, target)
    definition = _definitions(package.root_definition)[binding["definition_id"]]
    shape = read_brep_shape(definition.blobs[definition.solid_cache_ref.path])
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    cylinders, planes, faces = [], 0, 0
    while explorer.More():
        surface = BRepAdaptor_Surface(TopoDS.Face_s(explorer.Current()))
        faces += 1
        if surface.GetType() == GeomAbs_Cylinder:
            cylinders.append(surface.Cylinder())
        elif surface.GetType() == GeomAbs_Plane:
            planes += 1
        explorer.Next()
    if len(cylinders) != 1 or planes != 2 or faces != 3:
        raise ValueError("geometry: automatic BREP reading supports a complete solid straight circular cylinder only; provide a CAD-derived planar centerline and diameter for another supported shape")
    cylinder = cylinders[0]
    radius = cylinder.Radius()
    direction = [cylinder.Axis().Direction().Coord(i + 1) for i in range(3)]
    if direction[max(range(3), key=lambda i: abs(direction[i]))] < 0:
        direction = [-x for x in direction]
    origin = [cylinder.Location().Coord(i + 1) for i in range(3)]
    stations = []
    explorer = TopExp_Explorer(shape, TopAbs_VERTEX)
    while explorer.More():
        point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(explorer.Current()))
        stations.append(sum((point.Coord(i + 1) - origin[i]) * direction[i] for i in range(3)))
        explorer.Next()
    if not stations:
        raise ValueError("geometry: cylinder has no evaluated vertices")
    low, high = min(stations), max(stations)
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    if high <= low or radius <= 0 or not math.isclose(abs(props.Mass()), math.pi * radius**2 * (high - low), rel_tol=1e-6, abs_tol=1e-8):
        raise ValueError("geometry: evaluated shape is not a complete solid circular cylinder")
    points = [_world([origin[i] + t * direction[i] for i in range(3)], binding["world_transform_m"]) for t in (low, high)]
    return {"centerline_m": points, "diameter_m": radius * .002,
            "method": "evaluated_brep_solid_cylinder", "brep_sha256": binding["brep_sha256"],
            "assumption": "Complete straight cylinder axis/length/radius read from evaluated CAD; no generic BREP medial-axis inference."}


def resolve_geometry(package, target, supplied=None, source=None):
    from .provenance import parameter, inherited, derived
    supplied = _closed(supplied or {}, {"centerline_m", "diameter_m", "free_start_m", "free_end_m", "source"}, "request.geometry")
    context = inherited(supplied, source, 'request.geometry.source')
    parameters = {key: parameter(value, 'm', 'request.geometry.' + key, context)
                  for key, value in supplied.items() if key != 'source'}
    supplied = {key: item['value'] for key, item in parameters.items()}
    explicit = "centerline_m" in supplied or "diameter_m" in supplied
    if explicit and not {"centerline_m", "diameter_m"} <= supplied.keys():
        raise ValueError("request.geometry: explicit geometry requires centerline_m, diameter_m and source")
    try:
        actual = read_cylinder(package, target)
    except ValueError:
        if not explicit:
            raise
        actual = None
    if explicit:
        points = supplied["centerline_m"]
        if not isinstance(points, list) or not 2 <= len(points) <= 100000:
            raise ValueError("request.geometry.centerline_m: require 2..100000 world-SI points")
        for point in points:
            if not isinstance(point, list) or len(point) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in point):
                raise ValueError("request.geometry.centerline_m: require finite 3D coordinates")
            for coordinate in point:
                _float32(coordinate, "request.geometry.centerline_m")
        diameter = _positive(supplied["diameter_m"], "request.geometry.diameter_m")
        if actual:
            tolerance = max(1e-8, diameter * 1e-5)
            ends = actual["centerline_m"]
            if not math.isclose(diameter, actual["diameter_m"], rel_tol=1e-6) or len(points) != 2 or min(
                max(math.dist(points[i], ends[i]) for i in (0, 1)),
                max(math.dist(points[i], ends[1-i]) for i in (0, 1))) > tolerance:
                raise ValueError("request.geometry: supplied geometry conflicts with the actual complete CAD cylinder")
        geometry = {"centerline_m": points, "diameter_m": diameter,
                    "method": "cad_bound_supplied_polyline", "brep_sha256": geometry_source_snapshot(package, target)["brep_sha256"],
                    "assumption": "Caller CAD-derived polyline; entire centerline containment is not verified against arbitrary BREP.",
                    "source": parameters['centerline_m']['source']}
    else:
        geometry = actual
        cad_source = {'kind': 'reference', 'detail': 'Read from the actual evaluated CAD cylinder',
            'citation': 'package:BREP/' + actual['brep_sha256'], 'conditions': 'Native mm evaluated solid with saved occurrence world transform'}
        for key in ('centerline_m', 'diameter_m'):
            parameters[key] = {'value': geometry[key], 'unit': 'm', 'source': cad_source}
    stations = [0.]
    for a, b in zip(geometry["centerline_m"], geometry["centerline_m"][1:]):
        distance = math.dist(a, b)
        if distance <= 1e-12:
            raise ValueError("request.geometry: coincident centerline points")
        stations.append(stations[-1] + distance)
    start = _positive(supplied.get("free_start_m", 0.), "request.geometry.free_start_m", zero=True)
    end = _positive(supplied.get("free_end_m", stations[-1]), "request.geometry.free_end_m")
    if not 0 <= start < end <= stations[-1]:
        raise ValueError("request.geometry: require 0<=free_start<free_end<=actual material length")
    geometry.update(length_m=stations[-1], arc_stations_m=stations, free_start_m=start, free_end_m=end,
                    free_length_m=end-start)
    parameters['length_m'] = derived('polyline-length-v1', {'centerline': parameters['centerline_m']}, 'Sum of supplied or CAD-read world-space polyline chords')
    parameters['arc_stations_m'] = derived('polyline-stations-v1', {'centerline': parameters['centerline_m']}, 'Cumulative world-space polyline arc stations')
    parameters.setdefault('free_start_m', {'value': 0., 'unit': 'm', 'source': {'kind': 'default', 'detail': 'Use the complete material interval from zero'}})
    parameters.setdefault('free_end_m', parameters['length_m'])
    parameters['free_length_m'] = derived('difference-v1', {'end': parameters['free_end_m'], 'start': parameters['free_start_m']}, 'Free material interval end minus start')
    geometry['parameters'] = parameters
    return geometry


def initial_curvature_radius(points):
    radii = []
    for a, b, c in zip(points, points[1:], points[2:]):
        u = [b[i]-a[i] for i in range(3)]
        v = [c[i]-b[i] for i in range(3)]
        cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        cross_norm = math.hypot(*cross)
        product = math.hypot(*u) * math.hypot(*v)
        if cross_norm <= 1e-12 * product:
            if sum(u[i]*v[i] for i in range(3)) < 0:
                raise ValueError("geometry: reversing polyline cusp is not supported")
            continue
        radii.append(product * math.dist(a, c) / (2*cross_norm))
    return min(radii) if radii else None

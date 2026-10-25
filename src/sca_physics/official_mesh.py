"""Validate persisted output of the official PhysX surface-to-volume mesher.

No meshing or cooking occurs here. The asset-building Isaac process owns the
official call; this dependency-free contract preserves its actual output.
"""

from collections import Counter
from copy import deepcopy
import json
import math
import hashlib
import struct

from .contract import _closed, _float32, _object

METHOD = "physx_conforming_tetrahedra"
OFFICIAL_API = "omni.physx.get_physx_cooking_interface().compute_conforming_tetrahedral_mesh"


def _sub(a, b):
    return [x-y for x, y in zip(a, b)]


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _det(a, b, c):
    return (a[0]*(b[1]*c[2]-b[2]*c[1])
            - a[1]*(b[0]*c[2]-b[2]*c[0])
            + a[2]*(b[0]*c[1]-b[1]*c[0]))


def validate_generated(raw, geometry, path, *, resolve=False, cad_source=None):
    allowed = {"points", "tets", "surface", "ends", "provenance", "reference_points", "centerline_embedding", "source_geometry_sha256", "mesh_cache_key", "mesh_sha256"}
    required = allowed - {"centerline_embedding", "source_geometry_sha256", "mesh_cache_key", "mesh_sha256"}
    if resolve:
        required -= {"reference_points"}
    obj = _closed(raw, allowed, path, required=required)
    result = deepcopy(dict(obj))
    if resolve and "reference_points" not in result:
        result["reference_points"] = deepcopy(result["points"])
    for name in ("points", "reference_points"):
        points = result[name]
        if not isinstance(points, list) or len(points) < 4:
            raise ValueError(f"{path}.{name}: expected at least four 3D points")
        for row, point in enumerate(points):
            if not isinstance(point, list) or len(point) != 3:
                raise ValueError(f"{path}.{name}[{row}]: expected a 3D point")
            for col, value in enumerate(point):
                _float32(value, f"{path}.{name}[{row}][{col}]")
    points = result["points"]
    if result["reference_points"] != points:
        raise ValueError(f"{path}.reference_points: this candidate requires the unstrained generated point positions")
    # Use the exact positions USD will store, including positivity checks after
    # float32 conversion. Do not silently reorient or otherwise repair cells.
    fpoints = [[_float32(value, path) for value in point] for point in points]
    for name, width in (("tets", 4), ("surface", 3)):
        rows = result[name]
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{path}.{name}: expected a nonempty array")
        seen = set()
        for row, vertices in enumerate(rows):
            if (not isinstance(vertices, list) or len(vertices) != width
                    or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(points) for i in vertices)
                    or len(set(vertices)) != width):
                raise ValueError(f"{path}.{name}[{row}]: invalid vertex indices")
            key = tuple(sorted(vertices))
            if key in seen:
                raise ValueError(f"{path}.{name}: duplicate cell")
            seen.add(key)
    boundary = Counter()
    used = set()
    for row, tet in enumerate(result["tets"]):
        a, b, c, d = [fpoints[i] for i in tet]
        if _det(_sub(b, a), _sub(c, a), _sub(d, a)) <= 0:
            raise ValueError(f"{path}.tets[{row}]: nonpositive signed rest volume after float32 storage")
        used.update(tet)
        for face in ((tet[0],tet[1],tet[2]),(tet[0],tet[1],tet[3]),(tet[0],tet[2],tet[3]),(tet[1],tet[2],tet[3])):
            boundary[tuple(sorted(face))] += 1
    if len(used) != len(points) or any(count > 2 for count in boundary.values()):
        raise ValueError(f"{path}.tets: unused points or nonmanifold volume faces")
    expected_surface = {face for face, count in boundary.items() if count == 1}
    actual_surface = {tuple(sorted(face)) for face in result["surface"]}
    if expected_surface != actual_surface:
        raise ValueError(f"{path}.surface: must equal the actual tetrahedron boundary")
    if "mesh_sha256" in result:
        digest = hashlib.sha256()
        for name, code in (("points", "f"), ("tets", "i"), ("surface", "i")):
            for row in result[name]:
                digest.update(struct.pack("<" + code * len(row), *row))
        if result["mesh_sha256"] != digest.hexdigest():
            raise ValueError(f"{path}.mesh_sha256: generated mesh payload digest mismatch")
    surface_vertices = {i for face in result["surface"] for i in face}
    ends = _closed(result["ends"], {"start", "end"}, path+".ends", required=True)
    centerline = geometry["centerline"]["value"]
    radius = geometry["diameter"]["value"] / 2
    tolerance = 2e-6
    # The legacy procedural cable IS this polygonal centreline tube. A real CAD
    # curve can depart from its measurement polyline by sagitta; its actual CAD
    # surface digest/enclosure is verified by the exporter instead of replacing
    # that geometry with a polygonal measurement envelope.
    if cad_source is None:
        for point in fpoints:
            best = math.inf
            for start, end in zip(centerline, centerline[1:]):
                span = _sub(end, start)
                fraction = min(1., max(0., _dot(_sub(point,start),span)/_dot(span,span)))
                best = min(best, math.dist(point, [start[i]+fraction*span[i] for i in range(3)]))
            if best > radius+tolerance:
                raise ValueError(f"{path}.points: vertex outside declared cable cross-section bounds")
    for endpoint, origin, neighbor in (("start",centerline[0],centerline[1]),("end",centerline[-1],centerline[-2])):
        indices = ends[endpoint]
        if (not isinstance(indices,list) or len(indices)<3 or len(set(indices))!=len(indices)
                or any(isinstance(i,bool) or not isinstance(i,int) or i not in surface_vertices for i in indices)):
            raise ValueError(f"{path}.ends.{endpoint}: expected unique surface vertex indices for an endpoint cross-section")
        actual_tangents = geometry.get("endpoint_tangents", {}).get("value")
        tangent = actual_tangents[0 if endpoint == "start" else 1] if actual_tangents is not None else _sub(neighbor, origin)
        tangent = [v/math.sqrt(_dot(tangent,tangent)) for v in tangent]
        expected = {i for i in surface_vertices
                    if abs(_dot(_sub(fpoints[i],origin),tangent)) <= tolerance
                    and math.dist(fpoints[i],origin) <= radius+tolerance}
        if set(indices) != expected:
            raise ValueError(f"{path}.ends.{endpoint}: must cover the actual generated endpoint cross-section")
    if set(ends["start"]) & set(ends["end"]):
        raise ValueError(f"{path}.ends: endpoint vertex selections overlap")
    if cad_source is not None and "centerline_embedding" in result:
        embedding = _object(result["centerline_embedding"], path + ".centerline_embedding")
        arrays = [embedding.get(name) for name in ("source_tet_ids", "tet_vertex_indices", "weights", "sample_points_m")]
        if any(not isinstance(array, list) for array in arrays) or not arrays[0] or len({len(array) for array in arrays}) != 1:
            raise ValueError(f"{path}.centerline_embedding: malformed material-point mapping arrays")
        for sample, (tet_id, indices, weights, query) in enumerate(zip(*arrays)):
            if isinstance(tet_id, bool) or not isinstance(tet_id, int) or not 0 <= tet_id < len(result["tets"]) or indices != result["tets"][tet_id]:
                raise ValueError(f"{path}.centerline_embedding[{sample}]: mapping references stale tetrahedron indices; rebuild after topology changes")
            if not isinstance(weights, list) or len(weights) != 4 or any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or not -1e-6 <= w <= 1+1e-6 for w in weights) or not math.isclose(sum(weights), 1, rel_tol=0, abs_tol=1e-8):
                raise ValueError(f"{path}.centerline_embedding[{sample}]: invalid or extrapolated barycentric weights")
            if not isinstance(query, list) or len(query) != 3:
                raise ValueError(f"{path}.centerline_embedding[{sample}]: expected 3D reference query")
            for value in query:
                _float32(value, path + ".centerline_embedding.query")
            reconstructed = [sum(weights[k] * fpoints[indices[k]][axis] for k in range(4)) for axis in range(3)]
            if math.dist(reconstructed, query) > 1e-8:
                raise ValueError(f"{path}.centerline_embedding[{sample}]: mapping does not reconstruct saved reference material point")
    provenance = _object(result["provenance"], path+".provenance")
    if provenance.get("method") != METHOD or provenance.get("api") != OFFICIAL_API:
        raise ValueError(f"{path}.provenance: requires official method and exact invoked api name")
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError(f"{path}: all generated data and provenance must be finite JSON data") from None
    return result

"""Minimal ideal rack/pinion mimic declaration, not a general transmission API."""

from copy import deepcopy
from .contract import _closed, _object, _source
from .joint_physics import parameter


def couplings(raw, config, *, resolve, source=None):
    """Freeze q_follower + gearing*q_reference + offset = 0 in SI.

    Only a native revolute reference and prismatic follower are supported.
    Backend topology and solved CAD initial-state consistency are exporter checks.
    """
    records = _object(raw, "couplings")
    result, followers = {}, set()
    fields = {"representation", "reference_joint_id", "follower_joint_id", "gearing", "offset", "source"}
    from .provenance import inherited
    for identity, raw_record in records.items():
        path = "couplings." + identity
        if not identity.strip():
            raise ValueError("couplings: require a nonempty coupling_id")
        record = _closed(raw_record, fields, path, required=fields - ({"source"} if resolve else set()))
        context = inherited(record, source, path + ".source")
        if record["representation"] != "mimic":
            raise ValueError(path + ".representation: only ideal mimic rack/pinion is implemented")
        reference, follower = record["reference_joint_id"], record["follower_joint_id"]
        for field, value, kind in (("reference_joint_id", reference, "revolute"), ("follower_joint_id", follower, "prismatic")):
            if not isinstance(value, str) or value not in config["joints"] or config["joints"][value]["joint_type"] != kind:
                raise ValueError(path + "." + field + ": expected a native " + kind + " joint_id")
        if reference == follower:
            raise ValueError(path + ": reference and follower joints must differ")
        if follower in followers:
            raise ValueError(path + ".follower_joint_id: each follower may have only one coupling owner")
        followers.add(follower)
        articulation = config["assembly"].get("articulation", {})
        if not articulation.get("enabled", {}).get("value", False):
            raise ValueError(path + ": mimic requires a requested enabled articulation")
        for joint_id in (reference, follower):
            if config["joints"][joint_id].get("motion", {}).get("value") != "limited":
                raise ValueError(path + ": both mimic joints require explicit finite limited motion")
        follower_config = config["joints"][follower]
        if follower_config.get("drive", {}).get("mode", {}).get("value", "off") != "off":
            raise ValueError(path + ": mimic follower must not have an independent active drive")
        if follower_config["damping"]["value"] != 0:
            raise ValueError(path + ": mimic follower passive damping must be zero; no independent DriveAPI")
        gearing = parameter(record["gearing"], "m/rad", "gearing", path + ".gearing", resolve=resolve, source=context)
        offset = parameter(record["offset"], "m", "offset", path + ".offset", resolve=resolve, source=context)
        if gearing["value"] == 0:
            raise ValueError(path + ".gearing: require a finite nonzero signed gearing")
        ref_config = config["joints"][reference]
        mapped = [-gearing["value"] * ref_config[key]["value"] - offset["value"] for key in ("lower_limit", "upper_limit")]
        lower, upper = (follower_config[key]["value"] for key in ("lower_limit", "upper_limit"))
        if max(min(mapped), lower) > min(max(mapped), upper):
            raise ValueError(path + ": reference/follower limited ranges have no feasible mimic position")
        result[identity] = {"representation": "mimic", "reference_joint_id": reference,
            "follower_joint_id": follower, "gearing": gearing, "offset": offset,
            "source": _source(context, path + ".source")}
    return deepcopy(result)

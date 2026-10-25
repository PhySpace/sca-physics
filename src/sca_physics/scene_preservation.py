"""Keep captured scene bytes; update only the changed root asset identity.

Re-tessellating an existing scene can change entity provenance across processes.
Use the public SCA scene/package value objects, canonical hash functions and
validators instead. No ZIP members are edited and no stale references survive.
"""

from copy import deepcopy


def attach_preserved_scene(original, bare):
    from simplecadapi.artifacts.assembly_definition import AssemblyDefinition
    from simplecadapi.artifacts.assembly_io import encode_assembly_definition
    from simplecadapi.artifacts.part_io import encode_part_definition
    from simplecadapi.artifacts.canonical import content_hash, sha256_bytes
    from simplecadapi.product.packages import ProductPackage, validate_product_package
    from simplecadapi.scene.canonical import canonical_json_bytes, with_scene_revision
    from simplecadapi.scene.product_scene import ProductScenePackage, validate_product_scene_package

    if original.scene_path is None:
        return bare
    root = bare.root_definition
    previous_scene = original.scene
    manifest = deepcopy(dict(previous_scene.manifest))
    blobs = dict(previous_scene.blobs)
    root_payload = (encode_assembly_definition(root) if isinstance(root, AssemblyDefinition)
                    else encode_part_definition(root))
    digest = sha256_bytes(root_payload)
    product = next(item for item in manifest["product_assets"] if item["definition_id"] == root.definition_id)
    old_uri = product["uri"]
    suffix = ".assembly.zip" if isinstance(root, AssemblyDefinition) else ".part.zip"
    new_uri = "products/sha256-" + digest.removeprefix("sha256:") + suffix
    product.update(uri=new_uri, sha256=digest, asset_id=digest,
                   byte_length=len(root_payload), content_hash=root.content_hash, revision=root.revision)
    del blobs[old_uri]
    blobs[new_uri] = root_payload
    record = next(item for item in manifest["definitions"] if item["definition_id"] == root.definition_id)
    record.update(content_hash=root.content_hash, revision=root.revision, product_asset_id=digest)
    for node in manifest["nodes"]:
        if node["definition_id"] == root.definition_id:
            node["properties"].update(content_hash=root.content_hash, revision=root.revision)
    scene = ProductScenePackage(manifest=with_scene_revision(manifest), blobs=blobs)
    validate_product_scene_package(scene)

    # The official bare builder generated the new definitions and occurrences.
    # Reuse original scene payload storage, with all lengths/digests revalidated.
    objects = dict(bare.objects)
    blob_records = {item["sha256"]: deepcopy(item) for item in bare.manifest["blobs"]}
    for item in original.manifest["blobs"]:
        previous = blob_records.get(item["sha256"])
        if previous is not None and previous != item:
            raise ValueError("original scene blob conflicts with the official rebuilt package")
        blob_records[item["sha256"]] = deepcopy(item)
        if item["storage"]["kind"] == "member":
            path = item["storage"]["path"]
            objects[path] = original.objects[path]
    projection = deepcopy(original.manifest["projections"]["scene"])
    payload = canonical_json_bytes(dict(scene.manifest))
    scene_path = projection["manifest"]["path"]
    objects[scene_path] = payload
    projection["manifest"].update(sha256=sha256_bytes(payload), byte_length=len(payload))
    projection["revision"] = scene.manifest["revision"]
    for asset in projection["assets"]:
        if asset["uri"] == old_uri:
            asset["uri"] = new_uri
    projection["assets"].sort(key=lambda item: item["uri"])
    final_manifest = deepcopy(dict(bare.manifest))
    final_manifest["projections"] = {"scene": projection}
    final_manifest["blobs"] = [blob_records[key] for key in sorted(blob_records)]
    final_manifest["content_hash"] = content_hash(final_manifest)
    package = ProductPackage(manifest=final_manifest, objects=objects, root_definition=root)
    validate_product_package(package)
    return package

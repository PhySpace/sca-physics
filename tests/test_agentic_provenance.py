"""New input authority, truthful derivations and unchanged legacy read semantics."""
from copy import deepcopy
import math
import json
from pathlib import Path
import pytest
from sca_physics import circle_rod
from sca_physics.contract import resolve_config, validate_config
from sca_physics.provenance import parameter, derived, validate_tree
from sca_physics.cable_resolution import resource_budget, budget_values
from sca_physics.cable_inference import configure_cable
from sca_physics.cable_contract import _group, MATERIAL
from test_contract import package
from test_cable_inference import cad

EST = {'kind': 'estimated', 'detail': 'Object-specific Agent estimate with stated assumptions'}
USER = {'kind': 'explicit', 'detail': 'User supplied this field'}


def test_schema_selection_keeps_current_agentic_contract():
    from sca_physics.rigid_chain import schema_for_chains
    assert schema_for_chains({}, current='1.7')=='1.7'


def test_root_group_and_field_source_order(package):
    cfg = resolve_config(package, {'source': EST, 'parts': {'node/assembly/a': {
        'contact': {'source': USER, 'static_friction': 0, 'restitution': {'value': 0, 'source': EST}},
        'rigid_body': {'gravity_enabled': False}}}})
    part = cfg['parts']['node/assembly/a']
    assert cfg['schema_version'] == '1.7'
    assert part['contact']['static_friction']['source'] == USER
    assert part['contact']['restitution']['source'] == EST
    assert part['rigid_body']['gravity_enabled']['source'] == EST
    assert part['contact']['dynamic_friction']['source']['kind'] == 'default'
    validate_config(package, cfg)
    import jsonschema
    schema = json.loads((Path(__file__).parents[1]/'schemas/sca-physics-1.7.schema.json').read_text())
    jsonschema.validate(cfg, schema)


@pytest.mark.parametrize('value', [0, False, {'value': 0}, {'value': False, 'unit': 'boolean'}])
def test_absent_source_is_never_claimed_as_user(value):
    with pytest.raises(ValueError, match='test.field.source'):
        parameter(value, 'boolean' if value is False or isinstance(value,dict) and value.get('value') is False else '1', 'test.field')


def test_circle_rod_is_replayable_and_rejects_forged_derived_records():
    result = circle_rod(diameter_m=.005, density_kg_m3=1200, youngs_modulus_pa=2e7, shear_modulus_pa=7e6, source=EST)
    assert result['linear_density']['value'] == pytest.approx(1200*math.pi*.005**2/4)
    assert result['bending_rigidity']['value'] == pytest.approx(2e7*math.pi*.005**4/64)
    assert result['torsional_rigidity']['value'] == pytest.approx(7e6*math.pi*.005**4/32)
    for item in result.values():
        assert item['source']['kind'] == 'derived'
        assert item['source']['derivation']['formula']
        assert parameter(json.loads(json.dumps(item)), item['unit'], 'serialized') == item
    bad_formula = deepcopy(result['linear_density'])
    bad_formula['source']['derivation']['formula'] = 'lambda = density'
    with pytest.raises(ValueError, match='formula'):
        parameter(bad_formula, 'kg/m', 'forged')
    missing_formula = deepcopy(result['linear_density'])
    del missing_formula['source']['derivation']['formula']
    with pytest.raises(ValueError, match='formula'):
        parameter(missing_formula, 'kg/m', 'forged')
    bad = deepcopy(result['bending_rigidity']); bad['value'] *= 2
    with pytest.raises(ValueError, match='derived'):
        parameter(bad, 'N*m^2', 'forged')
    with pytest.raises(ValueError):
        parameter({'value': 1, 'source': {'kind': 'derived', 'detail': 'No calculation'}}, '1', 'forged')
    with pytest.raises(ValueError, match='source'):
        circle_rod(diameter_m=.005, density_kg_m3=1200, youngs_modulus_pa=2e7, shear_modulus_pa=7e6)


def test_legacy_sources_and_budget_are_read_without_relabelling(package):
    old = resolve_config(package, {'schema_version': '1.0'})
    frozen = deepcopy(old)
    validate_config(package, old)
    assert old == frozen
    assert old['schema_version'] == '1.0'
    item = circle_rod(diameter_m=.005, density_kg_m3=1200, youngs_modulus_pa=2e7, shear_modulus_pa=7e6, source=EST)['linear_density']
    with pytest.raises(ValueError, match='1.7'):
        validate_tree(item, legacy=True)
    budget = resource_budget({}, partial=True, schema_version='1.6')
    frozen = deepcopy(budget)
    assert budget_values(budget) == budget
    assert budget == frozen


def test_fem_material_group_inherits_only_this_submissions_source():
    values = _group({'source': EST, 'density': 1200, 'youngs_modulus': 2e7, 'poissons_ratio': .3}, MATERIAL, 'material', {'density','youngs_modulus','poissons_ratio'}, resolve=True)
    assert values['density']['source'] == EST
    with pytest.raises(ValueError, match='material.density.source'):
        _group({'density': 1200}, MATERIAL, 'material', False, resolve=True)


def test_submitted_estimate_wins_presets_and_evidence(cad):
    pkg, target = cad
    cfg = configure_cable(pkg, target, {'description': 'Agent-selected suitable stranded construction',
        'category': 'stranded_wire', 'source': EST,
        'properties': {'linear_density': .027, 'bending_rigidity': .0008, 'gravity_magnitude': 0},
        'solver': {'solver_velocity_iterations': 0}, 'resource_budget': {'max_bodies': 300}})
    item = next(iter(cfg['cables'].values()))
    assert item['mechanics']['linear_density']['value'] == .027
    assert item['mechanics']['linear_density']['source'] == EST
    assert 'elastogravity_feature_m' not in item['resolution']['selection']['criteria']
    assert item['discretization']['free_segments']['source']['kind'] == 'derived'
    assert item['body']['solver_velocity_iterations']['source'] == EST
    assert item['resource_budget']['max_bodies']['source'] == EST
    assert item['resource_budget']['max_joints']['source']['kind'] == 'default'


def test_unknown_description_does_not_default_to_wire(cad):
    pkg, target = cad
    with pytest.raises(ValueError, match='category'):
        configure_cable(pkg, target, {'description': 'An unknown silicone object'})
    with pytest.raises(ValueError, match='source'):
        configure_cable(pkg, target, {'description': 'wire', 'category': 'stranded_wire', 'properties': {'linear_density': .02}})
    described=configure_cable(pkg,target,{'description':'stiffer 更硬','category':'stranded_wire'})
    normal=configure_cable(pkg,target,{'description':'normal','category':'stranded_wire'})
    assert next(iter(described['cables'].values()))['mechanics']==next(iter(normal['cables'].values()))['mechanics']


def test_density_conversion_and_count_sources(cad):
    pkg,target=cad
    cfg=configure_cable(pkg,target,{'description':'matched construction','category':'stranded_wire','source':EST,
        'properties':{'equivalent_density':1200},'discretization':{'mode':'explicit','free_segments':9}})
    item=next(iter(cfg['cables'].values()))
    assert item['mechanics']['linear_density']['source']['kind']=='derived'
    assert item['discretization']['free_segments']['source']==EST
    with pytest.raises(ValueError,match='mutually exclusive'):
        configure_cable(pkg,target,{'description':'wire','category':'stranded_wire','source':EST,
            'properties':{'equivalent_density':1200,'linear_density':.02}})


def test_reconfigure_group_sources_and_unchanged_estimates_are_preserved(cad):
    from sca_physics.package_io import enrich_package
    pkg,target=cad
    first=configure_cable(pkg,target,{'description':'matched wire','category':'stranded_wire','source':EST,
        'properties':{'linear_density':.027},'resource_budget':{'max_bodies':400}})
    saved,_=enrich_package(pkg,first)
    old=next(iter(first['cables'].values()))
    updated=configure_cable(saved,target,{'description':'task-specific revision',
        'properties':{'source':EST,'bending_rigidity':.002},
        'solver':{'source':USER,'physics_hz':1500}},reconfigure=True)
    new=next(iter(updated['cables'].values()))
    assert new['mechanics']['bending_rigidity']['value']==.002
    assert new['mechanics']['bending_rigidity']['source']==EST
    assert new['scene']['physics_hz']['source']==USER
    for group,key in [('mechanics','linear_density'),('mechanics','torsional_rigidity'),('body','linear_damping'),('discretization','free_segments')]:
        assert new[group][key]==old[group][key]
    assert new['resource_budget']==old['resource_budget']
    with pytest.raises(ValueError,match='source'):
        configure_cable(saved,target,{'description':'unlabelled edit','properties':{'linear_density':.03}},reconfigure=True)


def test_decision_binding_resolves_an_actual_saved_field(package):
    decision={'purpose':'Demonstrate saved reasoning','representation':'rigid_body','rationale':'Use existing native material',
        'bindings':[{'field':'/parts/node~1assembly~1a/contact/static_friction','material_id':'contact_pair_estimate','basis':'Object-specific dry contact assumption'}]}
    cfg=resolve_config(package,{'decision':decision})
    assert cfg['decision']==decision
    bad=deepcopy(cfg);bad['decision']['bindings'][0]['field']='/parts/missing/contact/static_friction'
    with pytest.raises(ValueError,match='bindings'):
        validate_config(package,bad)


def test_program_fillers_are_defaults_and_keep_their_engineering_basis(cad):
    pkg,target=cad
    cfg=configure_cable(pkg,target,{'description':'matched wire','category':'stranded_wire'})
    record=next(iter(cfg['cables'].values()))
    for group,key in [('mechanics','bending_rigidity'),('mechanics','joint_damping'),('body','linear_damping'),('scene','physics_hz')]:
        provenance=record[group][key]['source']
        if provenance['kind']=='derived':
            assert provenance['derivation']['inputs']['base']['source']['kind']=='default'
        else:
            assert provenance['kind']=='default'
    proof=record['discretization']['free_segments']['source']['derivation']
    assert proof['inputs']['target_length']['source']['kind']=='default'


def test_saved_user_authority_blocks_agent_updates_on_both_chain_entries(cad):
    from sca_physics.package_io import enrich_package
    from sca_physics.rigid_chain import upsert_rigid_chain
    pkg,target=cad
    first=configure_cable(pkg,target,{'description':'matched wire','category':'stranded_wire','source':USER,
        'properties':{'linear_density':.027}},chain_id='object')
    saved,_=enrich_package(pkg,first)
    with pytest.raises(ValueError,match='saved explicit user'):
        configure_cable(saved,target,{'description':'agent revision','properties':{'source':EST,'linear_density':.03}},reconfigure=True)
    accepted=configure_cable(saved,target,{'description':'user revision','properties':{'source':USER,'linear_density':.03}},reconfigure=True)
    assert accepted['cables']['object']['mechanics']['linear_density']['value']==.03
    declaration=deepcopy(first['cables']['object'])
    for key in ('resolution','geometry_source','parent_node_id','target_node_id','physical_type','representation'):
        declaration.pop(key,None)
    declaration['mechanics']['linear_density']={'value':.03,'unit':'kg/m','source':EST}
    with pytest.raises(ValueError,match='saved explicit user'):
        upsert_rigid_chain(saved,target,declaration)
    declaration['mechanics']['linear_density']=deepcopy(first['cables']['object']['mechanics']['linear_density'])
    declaration['decision']={'purpose':'Updated task reasoning','representation':'rigid_joint_chain','rationale':'Preserve user values',
        'bindings':[{'field':'/cables/object/mechanics/linear_density','material_id':'wire_equivalent','basis':'User-specified linear density'}]}
    result=upsert_rigid_chain(saved,target,declaration)
    assert result['decision']==declaration['decision']
    assert 'decision' not in result['cables']['object']


def test_lambda_density_family_preserves_user_authority_through_conversion(cad):
    from sca_physics.package_io import enrich_package
    pkg,target=cad
    first=configure_cable(pkg,target,{'description':'matched wire','category':'stranded_wire','source':USER,
        'properties':{'linear_density':.027}},chain_id='object')
    saved,_=enrich_package(pkg,first)
    with pytest.raises(ValueError,match='saved explicit user'):
        configure_cable(saved,target,{'description':'Agent density edit','source':EST,
            'properties':{'equivalent_density':1400}},reconfigure=True)
    changed=configure_cable(saved,target,{'description':'User density edit','source':USER,
        'properties':{'equivalent_density':1400}},reconfigure=True)
    line=changed['cables']['object']['mechanics']['linear_density']
    assert line['source']['kind']=='derived'
    assert line['source']['derivation']['inputs']['density']['source']==USER
    revised,_=enrich_package(saved,changed)
    with pytest.raises(ValueError,match='saved explicit user'):
        configure_cable(revised,target,{'description':'Agent later edit','source':EST,
            'properties':{'linear_density':.03}},reconfigure=True)

"""Small public-API controls, run in the verified paired USD interpreter.

Input is the raw package from run_task.py. This performs no simulator run and
never overwrites either package from that task. Keep the output as evidence.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    import simplecadapi as scad
    from sca_physics.cable_inference import configure_cable
    from sca_physics.contract import inventory
    from sca_physics.package_io import enrich_package
    from sca_usd_export import export_package
    from pxr import Usd,UsdPhysics
    raw=scad.read_product_package(args.raw)
    target=next(iter(inventory(raw)['parts']))
    user={'kind':'explicit','detail':'Control supplies a user numerical instruction, deliberately different from the preset'}
    agent={'kind':'estimated','detail':'Control supplies a documented Agent engineering estimate, deliberately different from the preset'}
    def request(source,value):
        return {'source':source,'description':'Public-interface control on a preset-compatible circular wire',
                'category':'stranded_wire','properties':{'linear_density':value},
                'discretization':{'mode':'explicit','free_segments':9}}
    def cable(config):return config['cables']['control']
    def resolve(req,package=raw,**kwargs):
        return configure_cable(package,target,req,chain_id='control',**kwargs)
    rows=[]
    def record(label,details):
        rows.append({'name':label,'passed':True,**details})
        (args.output/'controls-progress.json').write_text(json.dumps({'complete':False,'checks':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    def reject(label,req,match,package=raw,**kwargs):
        try:resolve(req,package,**kwargs)
        except ValueError as error:
            message=str(error)
            assert match in message,(label,message)
            record(label,{'expected_rejection':message,'request':req})
        else:raise AssertionError(label+' was not rejected')
    for label,source,value in [('user-over-preset',user,.023),('agent-over-preset',agent,.019)]:
        config=resolve(request(source,value))
        actual=cable(config)
        assert actual['mechanics']['linear_density']['value']==value
        assert actual['mechanics']['linear_density']['source']==source
        assert actual['discretization']['free_segments']['value']==9
        record(label,{'submitted':request(source,value),'saved':actual['mechanics']['linear_density'],
                      'explicit_n':actual['discretization']['free_segments']})
    zeros=request(agent,.019)
    zeros['properties'].update(joint_damping=0,linear_damping=0,angular_damping=0,
        restitution=0,self_collision=False,enabled=False,enable_speculative_ccd=False,apply_to_endpoints=False)
    result=cable(resolve(zeros))
    for group,keys in {'mechanics':['joint_damping'],'body':['linear_damping','angular_damping','enable_speculative_ccd','apply_to_endpoints'],
                       'contact':['restitution'],'collision':['enabled','self_collision']}.items():
        for key in keys:assert result[group][key]['value']==zeros['properties'][key]
    record('zero-and-false',{'submitted':zeros,'saved':result})
    rho=request(agent,.019)
    del rho['properties']['linear_density']
    rho['properties']['equivalent_density']=1700
    actual=cable(resolve(rho))['mechanics']['linear_density']
    assert math.isclose(actual['value'],1700*math.pi*.0026**2/4,rel_tol=1e-12)
    record('equivalent-density-controls-chain-mass',{'submitted':rho,'saved':actual})
    bad=request(agent,.019);del bad['source']
    reject('missing-source',bad,'source')
    bad=request(agent,.019);bad['properties']['equivalent_density']=1700
    reject('density-family-conflict',bad,'mutually exclusive')
    bad=request(agent,.019);bad['properties']['unknown_mechanic']=1
    reject('unknown-field',bad,'unknown')
    bad=request(agent,-1)
    reject('invalid-value-no-preset-fallback',bad,'nonnegative')
    bad=request(agent,.019);bad['discretization']['mode']='auto'
    reject('mode-conflict',bad,'free_segments')
    bad=request(agent,.019);bad.pop('category')
    reject('no-description-fallback',bad,'category')
    bad=request(agent,.019)
    bad['resource_budget']={'scope':'scene','max_bodies':2,'max_joints':1024,'max_colliders':1024,
        'max_filtered_pairs':4096,'max_contact_pairs':524288,'max_solver_work_per_second':1000000000}
    reject('budget-refusal-no-truncation',bad,'budget')
    frozen,_=enrich_package(raw,resolve(request(user,.023)))
    reject('agent-cannot-replace-saved-user',request(agent,.019),'explicit',package=frozen,reconfigure=True)
    revised=cable(resolve(request(user,.027),frozen,reconfigure=True))
    assert revised['mechanics']['linear_density']['value']==.027
    record('new-user-can-replace-saved-user',{'saved':revised['mechanics']['linear_density']})

    # Density is applied to actual native SCA Material, not an add-on label.
    masses=[]
    for density in (1000.,8000.):
        identifier='density_'+str(int(density))
        @scad.part(id=identifier)
        def block():
            item=scad.make_part_rpart(identifier,scad.make_box_rsolid(width=10,height=10,depth=10))
            native=scad.make_material_rmaterial(identifier+'_material',density=density,density_unit='kg/m^3')
            return scad.assign_material_rpart(item,native)
        definition=block()
        original=scad.build_product_package(definition)
        physical,_=enrich_package(original)
        package=args.output/(identifier+'.scadpkg')
        package.write_bytes(scad.encode_product_package(physical))
        digest=hashlib.sha256(package.read_bytes()).hexdigest()
        output=args.output/(identifier+'.usda')
        export_package(package,output,expected_input_sha256=digest,require_physics=True)
        stage=Usd.Stage.Open(str(output))
        actual_mass=sum(float(UsdPhysics.MassAPI(p).GetMassAttr().Get() or 0)
            for p in stage.Traverse() if p.HasAPI(UsdPhysics.MassAPI))
        assert math.isclose(actual_mass,density*1e-6,rel_tol=1e-5),(density,actual_mass)
        assert hashlib.sha256(package.read_bytes()).hexdigest()==digest
        masses.append({'density_kg_m3':density,'expected_kg':density*1e-6,'usd_kg':actual_mass})
    record('native-material-density-controls-rigid-mass',{'observations':masses})
    (args.output/'controls.json').write_text(json.dumps({'passed':True,'checks':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'checks':len(rows),'output':str(args.output)}))


if __name__=='__main__':main()

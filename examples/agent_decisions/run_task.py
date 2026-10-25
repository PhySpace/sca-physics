"""Execute an Agent's recorded decision using public SCA/add-on interfaces.

This runner does not interpret language or choose a material. The Agent supplies
a decision JSON with evidence and assumptions. Modeling, declaration preparation,
package reads and USD export run in separate installed interpreter processes.
"""
from __future__ import annotations
import argparse
import base64
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def val(item):
    return item['value'] if isinstance(item,dict) else item


def dimensions(decision):
    from sca_physics.provenance import derived
    return tuple(derived('mm-to-m-v1',{'length':decision['geometry'][key]},
        'Exact millimetre-to-metre conversion of the task dimension')
        for key in ('length_mm','diameter_mm'))


def worker(args):
    decision=load(args.decision)
    length,diameter=dimensions(decision)
    if args.worker=='model':
        import simplecadapi as scad
        from sca_physics.provenance import derived
        material=decision['material']
        density=material.get('density_kg_m3')
        if density is None:
            density=derived('density-from-linear-density-area-v1',{
                'linear_density':material['linear_density_kg_m'],'diameter':diameter},
                'Whole-object equivalent CAD density; not a claim of homogeneous copper/PVC')
        origin=decision['geometry']['origin_m']
        @scad.part(id='agent_task_part')
        def part():
            solid=scad.make_cylinder_rsolid(radius=val(decision['geometry']['diameter_mm'])/2,
                height=val(decision['geometry']['length_mm']),
                bottom_face_center=(-val(decision['geometry']['length_mm'])/2,0.,0.),axis=(1.,0.,0.))
            item=scad.make_part_rpart(part_id='agent_task_part',body=solid)
            native=scad.make_material_rmaterial(material_id=material['id'],name=material['name'],
                density=val(density),density_unit='kg/m^3',color=tuple(material['color']))
            return scad.assign_material_rpart(part=item,material=native)
        definition=part()
        @scad.assemble(id='agent_task_root',definitions=(definition,))
        def assembly():
            item=scad.make_assembly_rassembly(assembly_id='agent_task_root',name=decision['description'])
            placement=scad.make_placement_rplacement(origin=(
                val(origin)[0]*1000+val(decision['geometry']['length_mm'])/2,
                val(origin)[1]*1000,val(origin)[2]*1000))
            return scad.add_component_rassembly(assembly=item,item=definition.value,
                component_id='object',placement=placement)
        if args.package.exists():raise FileExistsError(args.package)
        result=scad.capture(assembly(),args.package)
        write(args.output,{'native_material_id':material['id'],'density':density,
            'length_m':length,'diameter_m':diameter,'raw_sha256':sha(args.package),
            'note':'Actual SCA Material density is authored through the public API, not a display-only field.'})
        print(json.dumps({'captured':str(args.package),'sha256':sha(args.package)}))
    elif args.worker=='prepare':
        from sca_physics import circle_rod
        from sca_physics.provenance import derived
        request=deepcopy(decision['physics'])
        request['decision']=deepcopy(decision['decision'])
        if decision['route']=='preset':
            request['description']=decision['description']
        elif decision['route']=='circle-rod':
            mechanics=circle_rod(diameter_m=diameter,density_kg_m3=decision['material']['density_kg_m3'],
                youngs_modulus_pa=decision['rod_material']['youngs_modulus_pa'],
                shear_modulus_pa=decision['rod_material']['shear_modulus_pa'])
            request['mechanics'].update(mechanics)
            n=derived('segment-count-v1',{'length':length,
                'target_length':decision['target_segment_length_m']},
                'Agent chose the initial target spacing for this task; ceil(length/spacing), not accuracy certification')
            request['discretization']['free_segments']=n
            origin=val(decision['geometry']['origin_m'])
            request['geometry'].update({'centerline':[origin,[origin[0]+val(length),origin[1],origin[2]]],
                'arc_stations':[0.,val(length)],'length':length,'free_start':0.,'free_end':length})
            radius=derived('scale-v1',{'base':diameter,'factor':{'value':.5,'unit':'1',
                'source':{'kind':'default','detail':'Exact radius/diameter identity, factor one half'}}},
                'Radius is half the specified diameter')
            request['section'].update({'radius':radius,'endpoint_radius':radius})
        else:raise ValueError('route must be preset or circle-rod; model suitability is an Agent decision')
        write(args.output,request)
        print(json.dumps({'prepared':str(args.output),'route':decision['route']}))
    elif args.worker=='verify':
        import simplecadapi as scad
        from pxr import Usd,UsdPhysics
        from sca_physics.contract import validate_config
        from sca_physics.package_io import preservation_report
        raw=scad.read_product_package(args.raw)
        final=scad.read_product_package(args.package)
        preserved=preservation_report(raw,final)
        config=final.root_definition.metadata['sca_physics']
        validate_config(final,config)
        assert config==load(args.expected),'Final metadata differs from saved snapshot'
        report=load(args.usd.with_suffix('.report.json'))
        assert report['input_package_sha256']==sha(args.package)
        chain=config['cables']['object']
        actual=report['physics']['rigid_chains'][0]
        assert actual['declaration']==chain,'USD report changed saved physics/provenance'
        n=val(chain['discretization']['free_segments'])
        extras=int(val(chain['geometry']['free_start'])>0)+int(val(chain['geometry']['free_end'])<val(chain['geometry']['length']))
        assert len(actual['links'])==n+extras
        assert sum(j['kind']=='internal_d6' for j in actual['joints'])==len(actual['links'])-1
        assert sum(j['kind']=='endpoint_fixed' for j in actual['joints'])==1
        stage=Usd.Stage.Open(str(args.usd))
        masses=[float(UsdPhysics.MassAPI(stage.GetPrimAtPath(p['path'])).GetMassAttr().Get()) for p in actual['links']]
        expected_mass=val(chain['mechanics']['linear_density'])*val(chain['geometry']['length'])
        assert math.isclose(sum(masses),expected_mass,rel_tol=1e-5),'Saved lambda did not control USD mass'
        result={'passed':True,'schema_version':config['schema_version'],'free_segments':n,
            'extra_endpoint_intervals':extras,'independent_endpoint_bodies':0,
            'dynamic_chain_bodies':len(masses),'expected_mass_kg':expected_mass,'usd_mass_kg':sum(masses),
            'declaration_and_sources_equal':True,'native_asset_preservation':preserved,
            'final_sha256':sha(args.package),'usd_sha256':sha(args.usd),'simulator_validated':False}
        write(args.output,result);print(json.dumps(result,ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decision',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--sca-python',type=Path)
    parser.add_argument('--home',type=Path)
    parser.add_argument('--skills-dir',type=Path)
    parser.add_argument('--worker',choices=('model','prepare','verify'),help=argparse.SUPPRESS)
    for key in ('package','raw','expected','usd'):parser.add_argument('--'+key,type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:return worker(args)
    if not all((args.sca_python,args.home,args.skills_dir)):parser.error('explicit --sca-python --home --skills-dir required')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'logs').mkdir()
    decision=load(args.decision);write(out/'decision.json',decision)
    script=out/'run_task.py';shutil.copy2(Path(__file__),script)
    env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','SCA_ADDON_DIR','SCA_RUNTIME_DIR','SCA_PHYSICS_SOURCE','SCA_USD_SOURCE'):
        env.pop(key,None)
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',SCA_ADDON_HOME=str(args.home.resolve()),
        SCA_SKILLS_DIR=str(args.skills_dir.resolve()))
    cli=[str(args.sca_python.resolve()),'-I','-B','-m','simplecadapi.cli']
    summary={'passed':False,'description':decision['description'],'commands':[],'simulator_validated':False}
    def run(label,argv,as_json=True):
        started=time.perf_counter()
        result=subprocess.run([str(x) for x in argv],cwd=out,env=env,capture_output=True,timeout=600)
        (out/'logs'/f'{label}.stdout.log').write_bytes(result.stdout)
        (out/'logs'/f'{label}.stderr.log').write_bytes(result.stderr)
        summary['commands'].append({'label':label,'argv':[str(x) for x in argv],
            'exit_code':result.returncode,'elapsed_s':time.perf_counter()-started})
        if result.returncode:raise RuntimeError(f'{label} failed; retained stdout/stderr contain the reason')
        return json.loads(result.stdout.decode('utf-8-sig')) if as_json else None
    def addon(name,label,*argv):
        token=base64.b64encode(json.dumps([str(x) for x in argv],ensure_ascii=False).encode('utf-8')).decode('ascii')
        if len(token)>6000:raise ValueError('Windows argument envelope too large; put configuration in a JSON file')
        return run(label,cli+['addon','use','--home',args.home.resolve(),'--skills-dir',args.skills_dir.resolve(),name,'argv-json-base64',token])
    try:
        facts={name:addon(name,'check-'+name,'check') for name in ('sca-physics','sca-usd-export')}
        write(out/'runtime-facts.json',facts)
        expected_versions = {'sca-physics': '0.1.8rc1', 'sca-usd-export': '0.1.8rc2'}
        for name,fact in facts.items():
            versions=fact.get('versions',fact.get('packages',{}))
            if (not fact['ok'] or versions.get(name) != expected_versions[name]
                    or versions.get('sca-physics') != expected_versions['sca-physics']):
                raise RuntimeError('Expected sca-physics 0.1.8rc1 with sca-usd-export 0.1.8rc2')
        physical_python=facts['sca-physics']['executable'];usd_python=facts['sca-usd-export']['executable']
        raw=out/'raw.scadpkg';final=out/'final.scadpkg';stage=out/'final.usda';request=out/'declaration.json'
        run('model',[physical_python,'-I','-B',script,'--worker','model','--decision',out/'decision.json',
            '--package',raw,'--output',out/'model-facts.json'])
        inventory=addon('sca-physics','inspect-raw','inspect',raw)
        parts=inventory['inventory']['parts']
        if len(parts)!=1 or inventory['sca_physics'] is not None:raise RuntimeError('Expected one fresh CAD occurrence without addon physics')
        target=next(iter(parts))
        run('prepare',[physical_python,'-I','-B',script,'--worker','prepare','--decision',out/'decision.json','--output',request])
        command='configure-cable' if decision['route']=='preset' else 'set-rigid-chain'
        saved=addon('sca-physics','save',command,raw,'--target',target,'--chain-id','object','--config',request,'--output',final)
        write(out/'expected-metadata.json',saved['sca_physics'])
        reread=addon('sca-physics','independent-read','inspect',final)
        if reread['sca_physics']!=saved['sca_physics']:raise RuntimeError('Independent read differs')
        addon('sca-physics','validate-final','validate',final,'--expect',out/'expected-metadata.json')
        final_hash=sha(final)
        addon('sca-usd-export','export','export',final,stage,'--require-physics','--expected-input-sha256',final_hash)
        addon('sca-usd-export','reopen-usd','validate',stage)
        if sha(final)!=final_hash:raise RuntimeError('Final package changed during independent export')
        checked=run('verify',[usd_python,'-I','-B',script,'--worker','verify','--decision',out/'decision.json',
            '--package',final,'--raw',raw,'--expected',out/'expected-metadata.json','--usd',stage,'--output',out/'verification.json'])
        summary.update(passed=True,verification=checked,final_package=str(final),usd=str(stage),
            final_sha256=final_hash,raw_sha256=sha(raw),decision_sha256=sha(out/'decision.json'))
    except Exception as error:
        summary['error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        write(out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

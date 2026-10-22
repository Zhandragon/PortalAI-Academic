"""Actual CPU solver/dispatcher/export with an explicit synthetic installation.

Never opens production accounts, starts models or consumes private input files.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Tools'), str(ROOT/'Agent'), str(ROOT)]
from validation_artifacts import ValidationArtifacts, require_output_space
import scientific_tool_bridge as bridge


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',type=Path,required=True)
    args=parser.parse_args()
    art=ValidationArtifacts(ROOT,args.artifacts_dir.resolve())
    require_output_space(ROOT,art,32*1024**2,for_outputs=True)
    fixture=art.path('physics-fixture-'+uuid.uuid4().hex[:8]);(fixture/'Agent').mkdir(parents=True)
    (fixture/'Agent/hardware_profiles.json').write_text((ROOT/'Agent/hardware_profiles.json').read_text())
    runtime_paths=bridge._science_paths();results=[]
    # Only path discovery changes. The actual operation, package layer, resource
    # checks, numerical integration, publishing and terminal-result envelope run.
    with patch.dict(os.environ), patch.object(bridge,'_root',return_value=fixture), patch.object(bridge,'_science_paths',return_value=runtime_paths):
        # The explicitly synthetic root must never inherit a live account or its
        # hydration capability. Restore the caller's environment on leaving.
        for name in ('PORTALAI_PROFILE_ID', 'PORTALAI_PROFILE_EPOCH',
                     'PORTALAI_HYDRATION_PORT', 'PORTALAI_HYDRATION_CAPABILITY',
                     'PORTALAI_HYDRATION_OWNER'):
            os.environ.pop(name, None)
        for dimensions in (2,3):
            result=bridge.run_science_request('physics.coupled_demo',kv=[f'dimensions={dimensions}','duration_s=0.5','frames=31'])
            assert result['success'] and result['_portableai']['terminal_result']
            assert result['metrics']['rigid_contact_samples']>0
            assert result['metrics']['maximum_relative_mass_transfer_error']<1e-12
            assert all(Path(path).is_file() and Path(path).is_relative_to(fixture) for path in result['files'])
            results.append(result)
            print(json.dumps({'dimensions':dimensions,'metrics':result['metrics'],'output_bytes':result['output_bytes']}),flush=True)
    # Scientific figure is derived only from these numeric synthetic trajectories.
    os.environ['MPLBACKEND']='Agg';os.environ['MPLCONFIGDIR']=str(art.path('plot-cache'))
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle
    fig,axes=plt.subplots(2,3,figsize=(12,8),facecolor='#17191b')
    for row,result in enumerate(results):
        trajectory=json.loads(Path(result['files'][0]).read_text())
        for ax,index in zip(axes[row],(0,15,30)):
            frame=trajectory['frames'][index];points=frame['positions'];dim=trajectory['config']['dimensions']
            ax.set_facecolor('#212326')
            ax.scatter([p[0] for p in points],[p[-1] for p in points],c=['#39b8df' if m==0 else '#f09683' for m in trajectory['materials']],s=6)
            ax.add_patch(Circle((frame['rigid_center'][0],frame['rigid_center'][-1]),trajectory['rigid_radius_m'],color='#d1a54b',alpha=.65))
            low,high=trajectory['tank_bounds_m'];ax.set_xlim(low-.025,high+.025);ax.set_ylim(low-.025,high+.025)
            ax.set_aspect('equal');ax.tick_params(colors='#e6dcc7');ax.set_title(f'{dim}D'+(' side projection' if dim==3 else '')+f" · {frame['time_s']:.2f} s",color='#e6c57a')
            for spine in ax.spines.values():spine.set_color('#b88a32')
    fig.suptitle('PortalAI coupled demo · approximate water-like / elastic / rigid mechanics',color='#e6c57a',fontsize=14)
    fig.tight_layout();fig.savefig(art.path('physics-demo.png'),dpi=120);plt.close(fig)
    report={'passed':True,'scope':'Actual Windows/host CPU integration and dispatcher with synthetic profile-free root; no model/GPU/VM/production accounts; not engineering accuracy validation.',
            'results':results,'preview':str(art.path('physics-demo.png'))}
    art.path('physics-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0


if __name__=='__main__':raise SystemExit(main())

# Science from Nice

Ask Nice in Chat to run a science operation. Expand the returned file card and
choose **Open** for an HTML scene, SVG diagram or data file.
HTML scenes open in your browser; CAD files need a compatible CAD or mesh
viewer. These are generated outputs, not additional main tabs in PortalAI.

The science tool requires an administrator account. The examples were executed
with Nice on Windows. Linux science requires its supported optional packages;
the first macOS package does not include the optional science runtime. Platform
availability is not implied by a screenshot. Models can choose the wrong tool
or misreport a result: inspect the actual tool return and files.

## Physics example

Ask Nice to load the science tool, read `physics.world_schema`, and then run
`physics.world` with a floor and falling boxes/spheres. Put the scene fields
directly inside `input`, without another `scene` wrapper. Each box dimension
must be between 0.1 and 10 metres. A fixed floor can use size `[10,1,10]`,
position `[0,-0.5,0]`, and mass `0`. Open the returned `world.html`.

The browser output includes Run/Pause, Reset, object controls and setup export.
The physics uses bounded educational approximations. It is not a structural,
combustion, CFD or engineering safety assessment.

## Biological sequence example

Ask Nice to run `plasmid.assemble` using `method:"annotated_join"`,
`circular:false`, and user-supplied named sequence parts. The returned
`assembly.svg` is a linearized feature map; `assembly.gb` and `assembly.fasta`
contain the annotated and plain sequences. The storefront example uses three
arbitrary synthetic teaching segments, including a reverse-strand segment.
Their labels do not imply biological function or experimentally validated
assembly. Other available operations cover sequence analysis, translation,
alignment, reference annotation and structure inspection.

## Chemistry, circuits and CAD

`chem.render` accepts a SMILES string and returns a 2D SVG plus computed
descriptors. `chem.conformer` exports a calculated SDF conformer, not an
experimentally measured structure. `electrical.dc` solves ideal circuits
containing resistors and current/voltage sources; node `"0"` is ground and
values use SI units. `cad.model` combines supported primitives using add/cut/
intersect and exports STEP/STL. Dimensions use millimetres. Inspect generated
designs with appropriate engineering tools before manufacturing or use.

## Repair notes

- Science JSON schemas retain nested objects and numeric limits through both
  serialization passes. Invalid scenes identify an indexed field and bounds.
- Nine existing CPU operations are available directly to the structured Chat
  tool, with input guidance in `science` operation `help`.
- Scientific documents now receive file cards with an explicit Open
  controls. HTML/SVG/CAD/data files are not automatically executed or decoded
  as media. Existing account/path restrictions remain.
- Reasoning checkpoint requests specify a short word target with output room.
  If summarization still ends early, original notes and tool outcomes remain
  saved and the existing bounded excerpt fallback is used. No tool replay or
  extra continuation allowance is introduced.
- No model weights, dependency pins or Academic edition restrictions change.

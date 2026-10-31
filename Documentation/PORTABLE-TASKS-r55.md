# Windows r55: lightweight general-task improvements

Nice now has `file_inspect`, a read-only standard-library tool that uses existing
account path permissions. It previews bounded text/CSV/JSON, SQLite schema and
ZIP/Office archive inventories, or searches literal text with exact character
offsets and continuation. It never extracts or executes archive/document content.
This helps Nice inspect unfamiliar files before choosing heavier science,
knowledge or media tools. Samples are explicitly labeled; they are not complete
dataset statistics. Documents remain untrusted evidence, never instructions.

`read_file` previously loaded the entire file before returning a small page.
It now streams 64 KiB character chunks, retaining only the requested page and
preserving UTF-8 replacement, universal newlines, exact total character count and
offset semantics. File changes, Stop and expired account access are checked.
Inspection is bounded to 20 seconds; long scans may need a narrower query.
Literal search returns up to 20 matches, scans at most 64 Mi characters beyond
the requested offset per call, and supplies next_offset when incomplete.

Preview reads at most 256 KiB; table samples cap rows, columns and cell text.
JSON is parsed only when it fits that sample. SQLite is opened read-only with
query-only/trusted-schema restrictions, a 2 MiB page cache, string/SQL/column
limits and a progress guard; only a bounded schema listing is queried. Archive
directory size and actual entry count are checked before zipfile builds objects
(4 MiB / 512 entries); at most 100 member descriptions are returned. Encrypted,
oversized or unsupported formats are reported without extraction or execution.

These features add no runtime, model, network service or background index. They
write no output files or persistent cache. Existing task progress and coding
recovery recognize their read-only nature; existing workflows, durable mission
checkpoints, knowledge retrieval and source discovery are retained.

Voice workers and installers continue to use the receiving SSD's storage policy,
including free-space floor and reserved output space. No safety margin is lowered
and no model/runtime deduplication or cross-drive dependency is introduced.

Source: ControlCenter/file_inspection.py, native_chat.py, task_progress.py,
coding_stall.py, tool_protocol.py and Agent/assistant_guidance.py.
Tests: Maintenance/Tests/test_file_inspection.py plus the existing tool protocol,
maintenance, task-progress and coding-stall suites. Tests include a multi-megabyte
Unicode file with peak traced allocations below 2 MiB, boundary-spanning search,
read-only SQLite, forged archive directory counts, cancellation and permissions.

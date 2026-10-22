"""Small current execution contracts, independent of catalog and private state."""

DIALOGUE_VIDEO = (
    'dialogue-video: arguments=[IMAGE,WORDS,"--duration","20","--motion",ACTION]. '
    'Duration is TOTAL video seconds (0.2..120), not speech length. '
    'Optional --dialogue-start SECONDS (default 0). Runtime measures natural speech; '
    'it must fit, with silence elsewhere. No speech/frame calculation is required. '
    'Optional --motion-plan JSON: [{"seconds":5,"prompt":"walk"},{"seconds":15,"prompt":"wave"}]; '
    'beat seconds sum to duration. Use media_tool; this syntax needs no prerequisite lookup.'
)


def execution_help(command):
    return DIALOGUE_VIDEO if command == 'dialogue-video' else ''

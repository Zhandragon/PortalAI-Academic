"""Keep a model program's bounded timeout distinct from grader infrastructure faults."""
import subprocess
from evaluation import grade as original_grade

def grade(case,text):
    try:
        return original_grade(case,text)
    except subprocess.TimeoutExpired:
        if case.get('kind')!='coding':raise
        return {'correct':False,'detail':{'passed':False,'timed_out':True,
                'reason':'Model program exceeded the five-second code execution budget; owned worker stopped.'}}
